from datetime import timedelta
from decimal import Decimal
import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from apps.checkout.models import CheckoutSession, CustomerOrder, OrderItem
from apps.finance.models import FinanceAccount, FinancePolicy, LedgerEntry, PayoutProfile, SettlementRequest
from apps.finance.services import account_balance, mark_settlement_paid, organization_account, recognize_order_finance, request_settlement, review_payout_profile, review_settlement
from apps.operations.models import FulfillmentRecord
from apps.organizations.models import Membership, Organization
from apps.storefront.models import ProductVariant, StoreProduct, Storefront, StudioProject
from apps.artwork.models import Artwork, ArtworkVersion, DesignedProduct
from apps.design.models import GarmentDesign, GarmentDesignVersion

User=get_user_model()

def delivered_order():
    owner=User.objects.create_user(username="fin-owner",password="password123"); customer=User.objects.create_user(username="fin-customer",password="password123")
    org=Organization.objects.create(kind="designer",display_name="Finance Brand",email="f@x.test",verification_status="active",created_by=owner); Membership.objects.create(organization=org,user=owner,role="owner")
    gd=GarmentDesign.objects.create(organization=org,title="T",status="approved",created_by=owner); gv=GarmentDesignVersion.objects.create(design=gd,version_number=1,status="approved",created_by=owner); art=Artwork.objects.create(organization=org,title="A",status="approved",created_by=owner); av=ArtworkVersion.objects.create(artwork=art,version_number=1,status="approved",created_by=owner); dp=DesignedProduct.objects.create(organization=org,garment_version=gv,artwork_version=av,title="P",status="published",created_by=owner)
    store=Storefront.objects.create(organization=org,slug="fin",status="published",name_en="Fin"); product=StoreProduct.objects.create(storefront=store,designed_product=dp,slug="p",status="published",title_en="P",base_price=Decimal("500.00"),currency="EGP",fulfillment_mode="stock"); variant=ProductVariant.objects.create(product=product,sku="FIN-1",stock_quantity=5); project=StudioProject.objects.create(customer=customer,product=product,variant=variant,status="ready",quantity=2); checkout=CheckoutSession.objects.create(customer=customer,studio_project=project,status="placed",subtotal=1000,total=1000,currency="EGP"); order=CustomerOrder.objects.create(checkout=checkout,customer=customer,designer_organization=org,status="confirmed",payment_method="cod",subtotal=1000,total=1000,currency="EGP",shipping_snapshot={}); OrderItem.objects.create(order=order,store_product=product,variant=variant,studio_project=project,sku=variant.sku,title="P",unit_price=500,quantity=2,line_total=1000); FulfillmentRecord.objects.create(order=order,status="delivered",delivered_at=timezone.now()); return owner,org,order

@pytest.mark.django_db
def test_delivered_order_recognized_once_with_policy_snapshot():
    owner,org,order=delivered_order(); FinancePolicy.objects.create(name="custom",platform_fee_bps=1000,settlement_delay_days=0,minimum_payout=100,is_active=True); r=recognize_order_finance(order=order,actor=owner); again=recognize_order_finance(order=order,actor=owner); assert r.pk==again.pk and r.gross_amount==1000 and r.platform_fee==100 and r.designer_earnings==900 and r.manufacturer_payable==0 and r.ledger_entries.count()==2

@pytest.mark.django_db
def test_balance_is_ledger_derived():
    owner,org,order=delivered_order(); FinancePolicy.objects.create(name="p",platform_fee_bps=1000,settlement_delay_days=0,minimum_payout=100,is_active=True); r=recognize_order_finance(order=order,actor=owner); b=account_balance(r.designer_account); assert b["available"]==Decimal("900.00") and b["withdrawable"]==Decimal("900.00")

@pytest.mark.django_db
def test_settlement_requires_verified_profile_and_reserves_balance():
    owner,org,order=delivered_order(); staff=User.objects.create_user(username="staff",password="password123",is_staff=True); FinancePolicy.objects.create(name="p",platform_fee_bps=1000,settlement_delay_days=0,minimum_payout=100,is_active=True); r=recognize_order_finance(order=order,actor=owner)
    with pytest.raises(ValidationError): request_settlement(organization=org,actor=owner,amount=200,currency="EGP")
    p=PayoutProfile.objects.create(organization=org,method="bank",account_holder="Owner",destination_hint="****1234",status="pending"); review_payout_profile(profile=p,reviewer=staff,decision="verified"); s=request_settlement(organization=org,actor=owner,amount=200,currency="EGP"); assert s.status=="requested" and account_balance(r.designer_account)["reserved"]==Decimal("200.00")

@pytest.mark.django_db
def test_paid_settlement_posts_single_debit():
    owner,org,order=delivered_order(); staff=User.objects.create_user(username="staff2",password="password123",is_staff=True); FinancePolicy.objects.create(name="p",platform_fee_bps=1000,settlement_delay_days=0,minimum_payout=100,is_active=True); r=recognize_order_finance(order=order,actor=owner); p=PayoutProfile.objects.create(organization=org,method="bank",account_holder="Owner",destination_hint="****1234",status="pending"); review_payout_profile(profile=p,reviewer=staff,decision="verified"); s=request_settlement(organization=org,actor=owner,amount=300,currency="EGP"); review_settlement(settlement=s,reviewer=staff,decision="approved"); mark_settlement_paid(settlement=s,reviewer=staff,external_reference="BANK-1"); assert LedgerEntry.objects.filter(settlement=s,entry_type="settlement",amount=Decimal("-300.00")).count()==1 and account_balance(r.designer_account)["available"]==Decimal("600.00")

@pytest.mark.django_db
def test_cross_tenant_finance_access_denied():
    owner,org,order=delivered_order(); other=User.objects.create_user(username="other-fin",password="password123"); otherorg=Organization.objects.create(kind="designer",display_name="Other",email="o@x.test",verification_status="active",created_by=other); Membership.objects.create(organization=otherorg,user=other,role="owner"); FinancePolicy.objects.create(name="p",platform_fee_bps=1000,settlement_delay_days=0,minimum_payout=100,is_active=True); recognize_order_finance(order=order,actor=owner); PayoutProfile.objects.create(organization=org,method="bank",account_holder="Owner",destination_hint="****1234",status="verified")
    with pytest.raises(PermissionDenied): request_settlement(organization=org,actor=other,amount=100,currency="EGP")
