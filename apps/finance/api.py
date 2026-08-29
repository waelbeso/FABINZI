from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.organizations.models import Membership, Organization
from .models import FinanceAccount, OrderFinance, PayoutProfile, SettlementRequest
from .services import account_balance, cancel_settlement, create_adjustment, organization_account, recognize_order_finance, request_settlement, review_payout_profile, review_settlement, mark_settlement_paid, update_payout_profile, require_finance_access


def _err(exc): return Response({"detail":str(exc)},status=403 if isinstance(exc,PermissionDenied) else 400)
def _settlement(s): return {"id":s.id,"organization_id":s.organization_id,"amount":s.amount,"currency":s.currency,"status":s.status,"requested_at":s.requested_at,"reviewed_at":s.reviewed_at,"paid_at":s.paid_at,"external_reference":s.external_reference}

class FinanceSummaryAPIView(APIView):
    def get(self,request,organization_id):
        org=get_object_or_404(Organization,pk=organization_id)
        try: require_finance_access(request.user,org)
        except PermissionDenied as exc: return _err(exc)
        accounts=FinanceAccount.objects.filter(organization=org)
        return Response({"organization_id":org.id,"accounts":[{"id":a.id,**account_balance(a)} for a in accounts],"settlements":[_settlement(s) for s in org.settlement_requests.all()[:50]]})

class PayoutProfileAPIView(APIView):
    def get(self,request,organization_id):
        org=get_object_or_404(Organization,pk=organization_id)
        try: require_finance_access(request.user,org)
        except PermissionDenied as exc: return _err(exc)
        p=PayoutProfile.objects.filter(organization=org).first(); return Response(None if not p else {"id":p.id,"method":p.method,"account_holder":p.account_holder,"destination_hint":p.destination_hint,"status":p.status,"verification_notes":p.verification_notes})
    def post(self,request,organization_id):
        try:
            p=update_payout_profile(organization=get_object_or_404(Organization,pk=organization_id),actor=request.user,method=request.data.get("method","bank"),account_holder=request.data.get("account_holder",""),destination_hint=request.data.get("destination_hint",""),submit=bool(request.data.get("submit",False)),request=request); return Response({"id":p.id,"status":p.status})
        except (PermissionDenied,ValidationError) as exc: return _err(exc)

class SettlementListCreateAPIView(APIView):
    def get(self,request,organization_id):
        org=get_object_or_404(Organization,pk=organization_id)
        try: require_finance_access(request.user,org)
        except PermissionDenied as exc: return _err(exc)
        return Response([_settlement(s) for s in org.settlement_requests.all()])
    def post(self,request,organization_id):
        try: return Response(_settlement(request_settlement(organization=get_object_or_404(Organization,pk=organization_id),actor=request.user,amount=request.data.get("amount","0"),currency=request.data.get("currency","EGP"),request=request)),status=201)
        except (PermissionDenied,ValidationError) as exc: return _err(exc)

class CancelSettlementAPIView(APIView):
    def post(self,request,settlement_id):
        try: return Response(_settlement(cancel_settlement(settlement=get_object_or_404(SettlementRequest,pk=settlement_id),actor=request.user,request=request)))
        except (PermissionDenied,ValidationError) as exc: return _err(exc)

class StaffPayoutReviewAPIView(APIView):
    def post(self,request,profile_id):
        try:
            p=review_payout_profile(profile=get_object_or_404(PayoutProfile,pk=profile_id),reviewer=request.user,decision=request.data.get("decision",""),notes=request.data.get("notes",""),request=request); return Response({"id":p.id,"status":p.status})
        except (PermissionDenied,ValidationError) as exc: return _err(exc)

class StaffSettlementReviewAPIView(APIView):
    def post(self,request,settlement_id):
        try: return Response(_settlement(review_settlement(settlement=get_object_or_404(SettlementRequest,pk=settlement_id),reviewer=request.user,decision=request.data.get("decision",""),notes=request.data.get("notes",""),request=request)))
        except (PermissionDenied,ValidationError) as exc: return _err(exc)

class StaffSettlementPaidAPIView(APIView):
    def post(self,request,settlement_id):
        try: return Response(_settlement(mark_settlement_paid(settlement=get_object_or_404(SettlementRequest,pk=settlement_id),reviewer=request.user,external_reference=request.data.get("external_reference",""),request=request)))
        except (PermissionDenied,ValidationError) as exc: return _err(exc)

class StaffRecognizeOrderAPIView(APIView):
    def post(self,request,order_id):
        if not request.user.is_staff: return Response({"detail":"Staff access required."},status=403)
        from apps.checkout.models import CustomerOrder
        try:
            r=recognize_order_finance(order=get_object_or_404(CustomerOrder,pk=order_id),actor=request.user,request=request); return Response({"id":r.id,"order_id":r.order_id,"gross_amount":r.gross_amount,"platform_fee":r.platform_fee,"manufacturer_payable":r.manufacturer_payable,"designer_earnings":r.designer_earnings,"currency":r.currency,"available_at":r.available_at})
        except ValidationError as exc: return _err(exc)

class StaffAdjustmentAPIView(APIView):
    def post(self,request,order_finance_id):
        try:
            record=get_object_or_404(OrderFinance,pk=order_finance_id); account=get_object_or_404(FinanceAccount,pk=request.data.get("account_id")); a=create_adjustment(order_finance=record,account=account,amount=request.data.get("amount","0"),reason=request.data.get("reason",""),actor=request.user,request=request); return Response({"id":a.id,"amount":a.amount,"reason":a.reason})
        except (PermissionDenied,ValidationError) as exc: return _err(exc)
