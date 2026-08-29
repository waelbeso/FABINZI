import hashlib
import json
import uuid
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from apps.audit.services import record_audit_event
from apps.integrations.models import IntegrationConfig
from apps.notifications.models import Notification
from apps.storefront.models import ProductVariant, StoreProduct, StudioProject
from apps.storefront.services import _validate_available_product, require_project_owner
from .gateways import create_remote_payment, get_payment_config
from .models import CheckoutSession, CustomerOrder, OrderItem, PaymentAttempt, PaymentWebhookEvent


def _money(value): return Decimal(value).quantize(Decimal("0.01"))

def _pricing(project):
    if not project.variant_id: raise ValidationError("A product variant is required for checkout.")
    _validate_available_product(project.product, project.variant, project.quantity)
    unit=_money(project.variant.price); subtotal=_money(unit*project.quantity)
    return unit, subtotal, Decimal("0.00"), Decimal("0.00"), subtotal

def _shipping_snapshot(session):
    return {"name":session.shipping_name,"phone":session.shipping_phone,"email":session.shipping_email,"address1":session.shipping_address1,"address2":session.shipping_address2,"city":session.shipping_city,"region":session.shipping_region,"country":session.shipping_country,"postal_code":session.postal_code}

def _customization_snapshot(project):
    if not hasattr(project,"customization") or not project.customization.enabled: return {}
    return {"enabled":True,"elements":[{"kind":e.kind,"zone_id":e.decoration_zone_id,"text":e.text,"media_asset_id":e.media_asset_id,"transform":e.transform,"style":e.style} for e in project.customization.elements.all()]}

def require_checkout_owner(actor, session):
    if not getattr(actor,"is_authenticated",False) or (session.customer_id != actor.pk and not actor.is_staff): raise PermissionDenied("Checkout access denied.")

def validate_shipping(session):
    required=[session.shipping_name,session.shipping_phone,session.shipping_address1,session.shipping_city,session.shipping_country]
    if any(not str(v).strip() for v in required): raise ValidationError("Name, phone, address, city and country are required.")

@transaction.atomic
def create_checkout(*, project, actor, request=None):
    require_project_owner(actor, project)
    if project.status != StudioProject.Status.READY: raise ValidationError("Studio project must be Ready for checkout.")
    unit,subtotal,shipping,discount,total=_pricing(project)
    session,created=CheckoutSession.objects.get_or_create(studio_project=project,defaults={"customer":project.customer,"subtotal":subtotal,"shipping_amount":shipping,"discount_amount":discount,"total":total,"currency":project.product.currency})
    if session.status != CheckoutSession.Status.DRAFT: raise ValidationError("This Studio project already has a finalized checkout.")
    session.subtotal=subtotal; session.shipping_amount=shipping; session.discount_amount=discount; session.total=total; session.currency=project.product.currency; session.full_clean(); session.save()
    record_audit_event(actor=actor,action="checkout.created" if created else "checkout.refreshed",instance=session,metadata={"project_id":project.pk},request=request)
    return session

@transaction.atomic
def update_checkout_shipping(*, session, actor, request=None, **fields):
    require_checkout_owner(actor,session)
    if session.status != CheckoutSession.Status.DRAFT: raise ValidationError("Finalized checkout sessions are immutable.")
    allowed={"shipping_name","shipping_phone","shipping_email","shipping_address1","shipping_address2","shipping_city","shipping_region","shipping_country","postal_code"}
    for key,value in fields.items():
        if key in allowed: setattr(session,key,value)
    session.full_clean(); session.save(); record_audit_event(actor=actor,action="checkout.shipping.updated",instance=session,request=request); return session

def _notify_order(order):
    Notification.objects.create(recipient=order.customer,type="order_status",title_en="Order confirmed",title_ar="تم تأكيد الطلب",body_en=f"Order {order.number} is confirmed.",body_ar=f"تم تأكيد الطلب {order.number}.",destination=f"/orders/{order.pk}/")

def _reserve_stock(order):
    item=order.item
    product=item.store_product
    if product.fulfillment_mode != StoreProduct.FulfillmentMode.STOCK: return
    variant=ProductVariant.objects.select_for_update().get(pk=item.variant_id)
    if variant.stock_quantity is not None:
        if variant.stock_quantity < item.quantity: raise ValidationError("Insufficient stock at payment confirmation.")
        variant.stock_quantity -= item.quantity; variant.save(update_fields=["stock_quantity"])

@transaction.atomic
def confirm_order(*, order, actor=None, request=None):
    order=CustomerOrder.objects.select_for_update().get(pk=order.pk)
    if order.status == CustomerOrder.Status.CONFIRMED: return order
    if order.status not in {CustomerOrder.Status.PENDING_PAYMENT,CustomerOrder.Status.PAYMENT_FAILED}: raise ValidationError("Order cannot be confirmed from its current state.")
    _reserve_stock(order); order.status=CustomerOrder.Status.CONFIRMED; order.confirmed_at=timezone.now(); order.save(update_fields=["status","confirmed_at","updated_at"]); _notify_order(order)
    record_audit_event(actor=actor,action="order.confirmed",instance=order,metadata={"payment_method":order.payment_method},request=request); return order

@transaction.atomic
def place_order(*, session, actor, payment_method, request=None):
    require_checkout_owner(actor,session)
    session=CheckoutSession.objects.select_for_update().get(pk=session.pk)
    if session.status != CheckoutSession.Status.DRAFT: raise ValidationError("Checkout has already been placed.")
    project=StudioProject.objects.select_related("product__storefront__organization","variant").get(pk=session.studio_project_id)
    validate_shipping(session); unit,subtotal,shipping,discount,total=_pricing(project)
    if payment_method not in dict(CustomerOrder.PaymentMethod.choices): raise ValidationError("Unsupported payment method.")
    get_payment_config(payment_method)
    order=CustomerOrder.objects.create(checkout=session,customer=session.customer,designer_organization=project.product.storefront.organization,status=CustomerOrder.Status.PENDING_PAYMENT,payment_method=payment_method,subtotal=subtotal,shipping_amount=shipping,discount_amount=discount,total=total,currency=project.product.currency,shipping_snapshot=_shipping_snapshot(session))
    OrderItem.objects.create(order=order,store_product=project.product,variant=project.variant,studio_project=project,sku=project.variant.sku,title=project.product.title_en,size=project.variant.size,color_name=project.variant.color_name,unit_price=unit,quantity=project.quantity,line_total=subtotal,customization_snapshot=_customization_snapshot(project))
    session.status=CheckoutSession.Status.PLACED; session.placed_at=timezone.now(); session.subtotal=subtotal; session.shipping_amount=shipping; session.discount_amount=discount; session.total=total; session.currency=project.product.currency; session.save(update_fields=["status","placed_at","subtotal","shipping_amount","discount_amount","total","currency","updated_at"])
    attempt=PaymentAttempt.objects.create(order=order,provider=payment_method,amount=total,currency=order.currency,idempotency_key=f"{payment_method}-{order.number}")
    if payment_method == CustomerOrder.PaymentMethod.COD:
        attempt.status=PaymentAttempt.Status.SUCCEEDED; attempt.completed_at=timezone.now(); attempt.provider_reference=f"COD-{order.number}"; attempt.save(update_fields=["status","completed_at","provider_reference","updated_at"]); order=confirm_order(order=order,actor=actor,request=request)
    record_audit_event(actor=actor,action="order.placed",instance=order,metadata={"payment_method":payment_method,"project_id":project.pk},request=request)
    return order,attempt

def initiate_online_payment(*, attempt, return_url=""):
    if attempt.provider == CustomerOrder.PaymentMethod.COD: raise ValidationError("COD does not require online initiation.")
    if attempt.status not in {PaymentAttempt.Status.PENDING,PaymentAttempt.Status.FAILED}: raise ValidationError("Payment attempt cannot be initiated.")
    try: data=create_remote_payment(attempt,return_url=return_url)
    except Exception as exc:
        attempt.status=PaymentAttempt.Status.FAILED; attempt.failure_code=exc.__class__.__name__; attempt.failure_message="Payment provider initiation failed."; attempt.save(update_fields=["status","failure_code","failure_message","updated_at"]); raise ValidationError("Payment provider initiation failed.") from exc
    attempt.provider_reference=data.get("reference",""); attempt.redirect_url=data.get("redirect_url",""); attempt.provider_payload={"client_secret":data.get("client_secret","")}; attempt.status=PaymentAttempt.Status.REQUIRES_ACTION; attempt.failure_code=""; attempt.failure_message=""; attempt.save(update_fields=["provider_reference","redirect_url","provider_payload","status","failure_code","failure_message","updated_at"]); return attempt

@transaction.atomic
def process_webhook(*, provider, event_id, payload_hash, reference, success, failed, payload):
    event,created=PaymentWebhookEvent.objects.get_or_create(provider=provider,event_id=event_id,defaults={"payload_hash":payload_hash})
    if not created:
        if event.payload_hash != payload_hash: raise ValidationError("Webhook event ID collision detected.")
        return event
    try:
        attempt=PaymentAttempt.objects.select_for_update().select_related("order").get(provider=provider,provider_reference=reference)
        if success:
            attempt.status=PaymentAttempt.Status.SUCCEEDED; attempt.completed_at=timezone.now(); attempt.failure_code=""; attempt.failure_message=""; attempt.save(update_fields=["status","completed_at","failure_code","failure_message","updated_at"]); confirm_order(order=attempt.order)
        elif failed:
            attempt.status=PaymentAttempt.Status.FAILED; attempt.failure_message="Provider reported payment failure."; attempt.completed_at=timezone.now(); attempt.save(update_fields=["status","failure_message","completed_at","updated_at"]); order=attempt.order; order.status=CustomerOrder.Status.PAYMENT_FAILED; order.save(update_fields=["status","updated_at"])
        event.processed=True; event.processed_at=timezone.now(); event.save(update_fields=["processed","processed_at"])
    except Exception as exc:
        event.processing_error=exc.__class__.__name__; event.save(update_fields=["processing_error"]); raise
    return event
