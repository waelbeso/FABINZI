import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError

from apps.artwork.models import Artwork, ArtworkVersion, DesignedProduct
from apps.design.models import GarmentDesign, GarmentDesignVersion
from apps.manufacturer_marketplace.models import ManufacturerListing, ManufacturerQuote, RFQ
from apps.manufacturer_marketplace.services import add_capability, create_rfq, get_or_create_listing, open_rfq, publish_listing, select_quote, submit_quote
from apps.organizations.models import Membership, Organization

User=get_user_model()


def org(user,kind,name,role="owner"):
    o=Organization.objects.create(kind=kind,display_name=name,email=f"{name.lower()}@x.test",verification_status=Organization.VerificationStatus.ACTIVE,created_by=user); Membership.objects.create(organization=o,user=user,role=role); return o


def published_product(designer,user):
    gd=GarmentDesign.objects.create(organization=designer,title="Tee",status=GarmentDesign.Status.APPROVED,created_by=user); gv=GarmentDesignVersion.objects.create(design=gd,version_number=1,status=GarmentDesignVersion.Status.APPROVED,created_by=user)
    a=Artwork.objects.create(organization=designer,title="Wave",status=Artwork.Status.APPROVED,created_by=user); av=ArtworkVersion.objects.create(artwork=a,version_number=1,status=ArtworkVersion.Status.APPROVED,created_by=user)
    return DesignedProduct.objects.create(organization=designer,garment_version=gv,artwork_version=av,title="Wave Tee",status=DesignedProduct.Status.PUBLISHED,created_by=user)


def published_manufacturer(user,name="Factory"):
    o=org(user,Organization.Kind.MANUFACTURER,name); listing=get_or_create_listing(organization=o,actor=user); listing.headline_en="Quality apparel manufacturing"; listing.save(); add_capability(listing=listing,actor=user,capability_type="cut_sew",name="T-shirts",min_quantity=50,max_quantity=10000,lead_time_days=14); publish_listing(listing=listing,actor=user); return o,listing


@pytest.mark.django_db
def test_only_active_manufacturer_can_publish_listing():
    u=User.objects.create_user(username="m",password="password123"); o=org(u,Organization.Kind.MANUFACTURER,"Factory"); listing=get_or_create_listing(organization=o,actor=u); listing.headline_en="Factory"; listing.save(); add_capability(listing=listing,actor=u,capability_type="cut_sew",name="Tee"); publish_listing(listing=listing,actor=u); assert listing.status==ManufacturerListing.Status.PUBLISHED


@pytest.mark.django_db
def test_listing_requires_capability_to_publish():
    u=User.objects.create_user(username="m",password="password123"); o=org(u,Organization.Kind.MANUFACTURER,"Factory"); listing=get_or_create_listing(organization=o,actor=u); listing.headline_en="Factory"; listing.save()
    with pytest.raises(ValidationError): publish_listing(listing=listing,actor=u)


@pytest.mark.django_db
def test_rfq_requires_published_owned_designed_product():
    d=User.objects.create_user(username="d",password="password123"); designer=org(d,Organization.Kind.DESIGNER,"Studio"); product=published_product(designer,d); product.status=DesignedProduct.Status.DRAFT; product.save()
    with pytest.raises(ValidationError): create_rfq(designer_organization=designer,actor=d,designed_product=product,title="Run",quantity=100)


@pytest.mark.django_db
def test_open_rfq_only_invites_eligible_published_manufacturer():
    d=User.objects.create_user(username="d",password="password123"); m=User.objects.create_user(username="m",password="password123"); designer=org(d,Organization.Kind.DESIGNER,"Studio"); product=published_product(designer,d); manufacturer,_=published_manufacturer(m); rfq=create_rfq(designer_organization=designer,actor=d,designed_product=product,title="Run",quantity=100); open_rfq(rfq=rfq,actor=d,manufacturer_ids=[manufacturer.pk]); assert rfq.status==RFQ.Status.OPEN and rfq.invitations.count()==1


@pytest.mark.django_db
def test_manufacturer_quote_and_designer_selection_flow():
    d=User.objects.create_user(username="d",password="password123"); m=User.objects.create_user(username="m",password="password123"); designer=org(d,Organization.Kind.DESIGNER,"Studio"); product=published_product(designer,d); manufacturer,_=published_manufacturer(m); rfq=create_rfq(designer_organization=designer,actor=d,designed_product=product,title="Run",quantity=100); open_rfq(rfq=rfq,actor=d,manufacturer_ids=[manufacturer.pk]); invitation=rfq.invitations.get(); quote=submit_quote(invitation=invitation,actor=m,unit_price="150.00",production_lead_days=15,minimum_order_quantity=50); assert quote.status==ManufacturerQuote.Status.SUBMITTED and rfq.status==RFQ.Status.QUOTED; selection=select_quote(quote=quote,actor=d); assert selection.manufacturer==manufacturer and rfq.status==RFQ.Status.SELECTED and quote.status==ManufacturerQuote.Status.ACCEPTED


@pytest.mark.django_db
def test_cross_tenant_manufacturer_cannot_quote_other_invitation():
    d=User.objects.create_user(username="d",password="password123"); m1=User.objects.create_user(username="m1",password="password123"); m2=User.objects.create_user(username="m2",password="password123"); designer=org(d,Organization.Kind.DESIGNER,"Studio"); product=published_product(designer,d); manufacturer,_=published_manufacturer(m1,"One"); published_manufacturer(m2,"Two"); rfq=create_rfq(designer_organization=designer,actor=d,designed_product=product,title="Run",quantity=100); open_rfq(rfq=rfq,actor=d,manufacturer_ids=[manufacturer.pk]);
    with pytest.raises(PermissionDenied): submit_quote(invitation=rfq.invitations.get(),actor=m2,unit_price="100",production_lead_days=10)


@pytest.mark.django_db
def test_quote_moq_cannot_exceed_rfq_quantity():
    d=User.objects.create_user(username="d",password="password123"); m=User.objects.create_user(username="m",password="password123"); designer=org(d,Organization.Kind.DESIGNER,"Studio"); product=published_product(designer,d); manufacturer,_=published_manufacturer(m); rfq=create_rfq(designer_organization=designer,actor=d,designed_product=product,title="Run",quantity=100); open_rfq(rfq=rfq,actor=d,manufacturer_ids=[manufacturer.pk]);
    with pytest.raises(ValidationError): submit_quote(invitation=rfq.invitations.get(),actor=m,unit_price="100",production_lead_days=10,minimum_order_quantity=101)
