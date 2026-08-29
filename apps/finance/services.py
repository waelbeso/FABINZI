from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.services import record_audit_event
from apps.notifications.models import Notification
from apps.operations.models import FulfillmentRecord
from apps.organizations.models import Membership
from apps.organizations.services import require_org_access
from .models import FinanceAccount, FinanceAdjustment, FinancePolicy, LedgerEntry, OrderFinance, PayoutProfile, SettlementRequest

FINANCE_ROLES=[Membership.Role.OWNER,Membership.Role.MANAGER,Membership.Role.ACCOUNTANT]
OPEN_SETTLEMENT={SettlementRequest.Status.REQUESTED,SettlementRequest.Status.APPROVED}


def _money(v): return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def active_policy():
    return FinancePolicy.objects.filter(is_active=True).order_by("id").first() or FinancePolicy.objects.create(name="default",platform_fee_bps=1000,settlement_delay_days=7,minimum_payout=Decimal("100.00"),is_active=True)

def organization_account(organization,currency):
    account,_=FinanceAccount.objects.get_or_create(account_type=FinanceAccount.AccountType.ORGANIZATION,organization=organization,currency=currency.upper())
    return account

def platform_account(currency):
    account=FinanceAccount.objects.filter(account_type=FinanceAccount.AccountType.PLATFORM,organization__isnull=True,currency=currency.upper()).first()
    if account: return account
    account=FinanceAccount(account_type=FinanceAccount.AccountType.PLATFORM,currency=currency.upper()); account.full_clean(); account.save(); return account

def require_finance_access(actor,organization):
    if getattr(actor,"is_staff",False): return
    require_org_access(actor,organization,roles=FINANCE_ROLES)

def account_balance(account,at=None):
    now=at or timezone.now()
    total=account.ledger_entries.aggregate(v=Sum("amount"))["v"] or Decimal("0.00")
    available=account.ledger_entries.filter(available_at__lte=now).aggregate(v=Sum("amount"))["v"] or Decimal("0.00")
    pending=total-available
    reserved=account.settlement_requests.filter(status__in=OPEN_SETTLEMENT).aggregate(v=Sum("amount"))["v"] or Decimal("0.00")
    withdrawable=max(Decimal("0.00"),available-reserved)
    return {"currency":account.currency,"total":_money(total),"available":_money(available),"pending":_money(pending),"reserved":_money(reserved),"withdrawable":_money(withdrawable)}

@transaction.atomic
def recognize_order_finance(*,order,actor=None,request=None):
    existing=OrderFinance.objects.filter(order=order).first()
    if existing: return existing
    fulfillment=FulfillmentRecord.objects.select_for_update().filter(order=order).first()
    if not fulfillment or fulfillment.status!=FulfillmentRecord.Status.DELIVERED or not fulfillment.delivered_at:
        raise ValidationError("Finance can only be recognized after delivery.")
    policy=active_policy(); currency=order.currency.upper(); designer_account=organization_account(order.designer_organization,currency)
    gross=_money(order.total); fee=_money(gross*Decimal(policy.platform_fee_bps)/Decimal(10000)); manufacturer_payable=Decimal("0.00"); manufacturer_account=None
    job=getattr(order,"production_job",None)
    if job and job.manufacturer_id and job.selection_id:
        quote=job.selection.quote
        if quote.currency.upper()!=currency: raise ValidationError("Manufacturer quote currency must match the customer order currency for automatic recognition.")
        manufacturer_payable=_money(quote.unit_price*order.item.quantity); manufacturer_account=organization_account(job.manufacturer,currency)
    designer_earnings=_money(gross-fee-manufacturer_payable); recognized=fulfillment.delivered_at; available_at=recognized+timedelta(days=policy.settlement_delay_days)
    record=OrderFinance.objects.create(order=order,designer_account=designer_account,manufacturer_account=manufacturer_account,gross_amount=gross,platform_fee=fee,manufacturer_payable=manufacturer_payable,designer_earnings=designer_earnings,currency=currency,policy_snapshot={"policy_id":policy.pk,"platform_fee_bps":policy.platform_fee_bps,"settlement_delay_days":policy.settlement_delay_days,"minimum_payout":str(policy.minimum_payout)},recognized_at=recognized,available_at=available_at)
    LedgerEntry.objects.create(account=designer_account,order_finance=record,entry_type=LedgerEntry.EntryType.DESIGNER_EARNING,amount=designer_earnings,currency=currency,available_at=available_at,memo=f"Order {order.number}",created_by=actor if getattr(actor,"is_authenticated",False) else None)
    if manufacturer_account and manufacturer_payable:
        LedgerEntry.objects.create(account=manufacturer_account,order_finance=record,entry_type=LedgerEntry.EntryType.MANUFACTURER_EARNING,amount=manufacturer_payable,currency=currency,available_at=available_at,memo=f"Order {order.number}",created_by=actor if getattr(actor,"is_authenticated",False) else None)
    LedgerEntry.objects.create(account=platform_account(currency),order_finance=record,entry_type=LedgerEntry.EntryType.PLATFORM_FEE,amount=fee,currency=currency,available_at=available_at,memo=f"Order {order.number}",created_by=actor if getattr(actor,"is_authenticated",False) else None)
    record_audit_event(actor=actor,action="finance.order.recognized",instance=record,metadata={"order_id":order.pk,"gross":str(gross),"platform_fee":str(fee),"manufacturer_payable":str(manufacturer_payable),"designer_earnings":str(designer_earnings)},request=request)
    return record

@transaction.atomic
def update_payout_profile(*,organization,actor,method,account_holder,destination_hint,submit=False,request=None):
    require_finance_access(actor,organization)
    profile,_=PayoutProfile.objects.get_or_create(organization=organization,defaults={"account_holder":account_holder or organization.display_name,"destination_hint":destination_hint or "Not provided"})
    if profile.status==PayoutProfile.Status.VERIFIED and not getattr(actor,"is_staff",False): raise ValidationError("Verified payout profiles must be changed by staff.")
    profile.method=method; profile.account_holder=account_holder.strip(); profile.destination_hint=destination_hint.strip(); profile.status=PayoutProfile.Status.PENDING if submit else PayoutProfile.Status.DRAFT; profile.verification_notes=""; profile.verified_by=None; profile.verified_at=None; profile.full_clean(); profile.save()
    record_audit_event(actor=actor,action="finance.payout_profile.submitted" if submit else "finance.payout_profile.updated",instance=profile,request=request); return profile

@transaction.atomic
def review_payout_profile(*,profile,reviewer,decision,notes="",request=None):
    if not reviewer.is_staff: raise PermissionDenied("Staff access required.")
    if decision not in {PayoutProfile.Status.VERIFIED,PayoutProfile.Status.REJECTED}: raise ValidationError("Unsupported payout profile decision.")
    if profile.status!=PayoutProfile.Status.PENDING: raise ValidationError("Only pending payout profiles can be reviewed.")
    profile.status=decision; profile.verification_notes=notes; profile.verified_by=reviewer; profile.verified_at=timezone.now() if decision==PayoutProfile.Status.VERIFIED else None; profile.save()
    record_audit_event(actor=reviewer,action=f"finance.payout_profile.{decision}",instance=profile,request=request); return profile

@transaction.atomic
def request_settlement(*,organization,actor,amount,currency,request=None):
    require_finance_access(actor,organization); currency=currency.upper(); account=organization_account(organization,currency); profile=PayoutProfile.objects.filter(organization=organization,status=PayoutProfile.Status.VERIFIED).first()
    if not profile: raise ValidationError("A verified payout profile is required.")
    policy=active_policy(); amount=_money(amount)
    if amount<policy.minimum_payout: raise ValidationError(f"Minimum settlement is {policy.minimum_payout}.")
    balance=account_balance(account)
    if amount>balance["withdrawable"]: raise ValidationError("Settlement amount exceeds withdrawable balance.")
    settlement=SettlementRequest(organization=organization,account=account,payout_profile=profile,amount=amount,currency=currency,payout_snapshot={"method":profile.method,"account_holder":profile.account_holder,"destination_hint":profile.destination_hint},requested_by=actor); settlement.full_clean(); settlement.save()
    record_audit_event(actor=actor,action="finance.settlement.requested",instance=settlement,metadata={"amount":str(amount)},request=request); return settlement

@transaction.atomic
def review_settlement(*,settlement,reviewer,decision,notes="",request=None):
    if not reviewer.is_staff: raise PermissionDenied("Staff access required.")
    if settlement.status!=SettlementRequest.Status.REQUESTED: raise ValidationError("Only requested settlements can be reviewed.")
    if decision not in {SettlementRequest.Status.APPROVED,SettlementRequest.Status.REJECTED}: raise ValidationError("Unsupported settlement decision.")
    settlement.status=decision; settlement.reviewed_by=reviewer; settlement.reviewed_at=timezone.now(); settlement.review_notes=notes; settlement.save()
    record_audit_event(actor=reviewer,action=f"finance.settlement.{decision}",instance=settlement,request=request); return settlement

@transaction.atomic
def mark_settlement_paid(*,settlement,reviewer,external_reference,request=None):
    if not reviewer.is_staff: raise PermissionDenied("Staff access required.")
    settlement=SettlementRequest.objects.select_for_update().get(pk=settlement.pk)
    if settlement.status!=SettlementRequest.Status.APPROVED: raise ValidationError("Only approved settlements can be marked paid.")
    if not external_reference.strip(): raise ValidationError("External settlement reference is required.")
    settlement.status=SettlementRequest.Status.PAID; settlement.paid_by=reviewer; settlement.paid_at=timezone.now(); settlement.external_reference=external_reference.strip(); settlement.save()
    LedgerEntry.objects.create(account=settlement.account,settlement=settlement,entry_type=LedgerEntry.EntryType.SETTLEMENT,amount=-settlement.amount,currency=settlement.currency,available_at=timezone.now(),memo=f"Settlement {settlement.pk}",created_by=reviewer)
    Notification.objects.bulk_create([Notification(recipient=m.user,type="finance_settlement",title_en="Settlement paid",title_ar="تم سداد التسوية",body_en=f"Settlement {settlement.amount} {settlement.currency} was paid.",body_ar=f"تم سداد تسوية بقيمة {settlement.amount} {settlement.currency}.",destination="/finance/") for m in settlement.organization.memberships.filter(is_active=True,role__in=FINANCE_ROLES).select_related("user")])
    record_audit_event(actor=reviewer,action="finance.settlement.paid",instance=settlement,metadata={"external_reference":settlement.external_reference},request=request); return settlement

@transaction.atomic
def cancel_settlement(*,settlement,actor,request=None):
    require_finance_access(actor,settlement.organization)
    if settlement.status!=SettlementRequest.Status.REQUESTED: raise ValidationError("Only requested settlements can be cancelled.")
    settlement.status=SettlementRequest.Status.CANCELLED; settlement.save(update_fields=["status"]); record_audit_event(actor=actor,action="finance.settlement.cancelled",instance=settlement,request=request); return settlement

@transaction.atomic
def create_adjustment(*,order_finance,account,amount,reason,actor,request=None):
    if not actor.is_staff: raise PermissionDenied("Staff access required.")
    adjustment=FinanceAdjustment(order_finance=order_finance,account=account,amount=_money(amount),reason=reason.strip(),created_by=actor); adjustment.full_clean(); adjustment.save(); LedgerEntry.objects.create(account=account,order_finance=order_finance,entry_type=LedgerEntry.EntryType.ADJUSTMENT,amount=adjustment.amount,currency=account.currency,available_at=timezone.now(),memo=reason.strip(),created_by=actor); record_audit_event(actor=actor,action="finance.adjustment.created",instance=adjustment,metadata={"amount":str(adjustment.amount)},request=request); return adjustment
