import hashlib
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.integrations.models import IntegrationConfig
from apps.storefront.models import StudioProject
from .gateways import get_payment_config, parse_webhook, verify_paymob_signature, verify_stripe_signature
from .models import CheckoutSession, CustomerOrder, PaymentAttempt
from .services import create_checkout, initiate_online_payment, place_order, process_webhook, require_checkout_owner, update_checkout_shipping


def _err(exc): return Response({"detail":str(exc)},status=403 if isinstance(exc,PermissionDenied) else 400)
def _checkout_data(s): return {"id":s.pk,"status":s.status,"studio_project":s.studio_project_id,"subtotal":s.subtotal,"shipping_amount":s.shipping_amount,"discount_amount":s.discount_amount,"total":s.total,"currency":s.currency,"shipping": {"name":s.shipping_name,"phone":s.shipping_phone,"email":s.shipping_email,"address1":s.shipping_address1,"address2":s.shipping_address2,"city":s.shipping_city,"region":s.shipping_region,"country":s.shipping_country,"postal_code":s.postal_code}}
def _order_data(o): return {"id":o.pk,"number":str(o.number),"status":o.status,"payment_method":o.payment_method,"total":o.total,"currency":o.currency,"created_at":o.created_at}

class CheckoutCreateAPIView(APIView):
    def post(self,request,project_id):
        try: return Response(_checkout_data(create_checkout(project=get_object_or_404(StudioProject,pk=project_id),actor=request.user,request=request)),status=201)
        except (ValidationError,PermissionDenied) as exc: return _err(exc)
class CheckoutDetailAPIView(APIView):
    def get(self,request,checkout_id):
        s=get_object_or_404(CheckoutSession.objects.select_related("studio_project"),pk=checkout_id)
        try: require_checkout_owner(request.user,s)
        except PermissionDenied as exc: return _err(exc)
        return Response(_checkout_data(s))
    def patch(self,request,checkout_id):
        s=get_object_or_404(CheckoutSession,pk=checkout_id)
        try: return Response(_checkout_data(update_checkout_shipping(session=s,actor=request.user,request=request,**request.data)))
        except (ValidationError,PermissionDenied) as exc: return _err(exc)
class PlaceOrderAPIView(APIView):
    def post(self,request,checkout_id):
        try:
            order,attempt=place_order(session=get_object_or_404(CheckoutSession,pk=checkout_id),actor=request.user,payment_method=request.data.get("payment_method","cod"),request=request)
            if attempt.provider != "cod" and request.data.get("initiate",True): initiate_online_payment(attempt=attempt,return_url=request.data.get("return_url",""))
            return Response({"order":_order_data(order),"payment":{"id":attempt.pk,"status":attempt.status,"provider":attempt.provider,"redirect_url":attempt.redirect_url,"client_secret":attempt.provider_payload.get("client_secret","")}},status=201)
        except (ValidationError,PermissionDenied) as exc: return _err(exc)
class OrderListAPIView(APIView):
    def get(self,request): return Response([_order_data(o) for o in CustomerOrder.objects.filter(customer=request.user)])
class OrderDetailAPIView(APIView):
    def get(self,request,order_id):
        o=get_object_or_404(CustomerOrder,pk=order_id)
        if o.customer_id!=request.user.pk and not request.user.is_staff: return Response({"detail":"Order access denied."},status=403)
        return Response(_order_data(o)|{"shipping":o.shipping_snapshot,"item":{"sku":o.item.sku,"title":o.item.title,"quantity":o.item.quantity,"unit_price":o.item.unit_price,"line_total":o.item.line_total}})
class PaymentOptionsAPIView(APIView):
    def get(self,request):
        rows=[]
        for p,label in CustomerOrder.PaymentMethod.choices:
            try: cfg=IntegrationConfig.objects.get(provider=p); available=cfg.enabled and (p=="cod" or cfg.last_test_status==IntegrationConfig.TestStatus.SUCCESS)
            except IntegrationConfig.DoesNotExist: available=False
            rows.append({"provider":p,"label":label,"available":available})
        return Response(rows)
class PaymentWebhookAPIView(APIView):
    permission_classes=[AllowAny]; authentication_classes=[]
    def post(self,request,provider):
        if provider not in {"stripe","paymob"}: return Response({"detail":"Unsupported provider."},status=404)
        try:
            cfg=get_payment_config(provider); secrets=cfg.get_secrets(); raw=request.body
            if provider=="stripe": valid=verify_stripe_signature(raw,request.headers.get("Stripe-Signature",""),secrets.get("webhook_secret",""))
            else: valid=verify_paymob_signature(raw,request.headers.get("X-FABINZI-Signature","") or request.query_params.get("hmac",""),secrets.get("webhook_hmac_secret","") or secrets.get("hmac_secret",""))
            if not valid: return Response({"detail":"Invalid webhook signature."},status=400)
            payload,event_id,reference,success,failed=parse_webhook(provider,raw)
            event=process_webhook(provider=provider,event_id=event_id,payload_hash=hashlib.sha256(raw).hexdigest(),reference=reference,success=success,failed=failed,payload=payload)
            return Response({"received":True,"processed":event.processed})
        except (ValidationError,ValueError) as exc: return Response({"detail":str(exc)},status=400)
