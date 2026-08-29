import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError

from apps.artwork.models import Artwork, ArtworkAsset, ArtworkReview, ArtworkVersion, DesignedProduct, IPCase, IPDeclaration
from apps.artwork.services import add_artwork_asset, add_product_placement, create_artwork, create_designed_product, create_ip_case, moderate_ip_case, publish_designed_product, review_artwork_version, set_ip_declaration, submit_artwork_version
from apps.design.models import DecorationZone, GarmentDesign, GarmentDesignVersion
from apps.media.models import MediaAsset
from apps.organizations.models import Membership, Organization

User = get_user_model()


def active_designer(user, name="Studio"):
    org = Organization.objects.create(kind=Organization.Kind.DESIGNER, display_name=name, email=f"{name.lower()}@x.test", verification_status=Organization.VerificationStatus.ACTIVE, created_by=user)
    Membership.objects.create(organization=org, user=user, role=Membership.Role.OWNER)
    return org


def approved_garment(org, user):
    d = GarmentDesign.objects.create(organization=org, title="Tee", created_by=user, status=GarmentDesign.Status.APPROVED)
    v = GarmentDesignVersion.objects.create(design=d, version_number=1, created_by=user, status=GarmentDesignVersion.Status.APPROVED)
    z = DecorationZone.objects.create(version=v, name="Front", method=DecorationZone.Method.PRINT, placement={"x":0.5,"y":0.4})
    return v, z


def complete_artwork(org, user):
    artwork = create_artwork(organization=org, actor=user, title="Wave")
    v = artwork.versions.get()
    preview = MediaAsset.objects.create(provider="cloudflare_images", provider_asset_id="preview", original_filename="preview.png", mime_type="image/png", size_bytes=10, access="public", uploaded_by=user)
    source = MediaAsset.objects.create(provider="amazon_s3", provider_asset_id="source.ai", original_filename="source.ai", mime_type="application/postscript", size_bytes=10, access="private", uploaded_by=user)
    add_artwork_asset(version=v, actor=user, media_asset=preview, kind=ArtworkAsset.Kind.PREVIEW)
    add_artwork_asset(version=v, actor=user, media_asset=source, kind=ArtworkAsset.Kind.SOURCE)
    set_ip_declaration(version=v, actor=user, rights_basis=IPDeclaration.RightsBasis.ORIGINAL, rights_holder_name="Creator", accepts_ip_policy=True)
    return artwork, v


@pytest.mark.django_db
def test_artwork_submission_and_review_flow():
    user=User.objects.create_user(username="artist",password="password123"); staff=User.objects.create_user(username="staff",password="password123",is_staff=True); org=active_designer(user)
    artwork,v=complete_artwork(org,user); submit_artwork_version(version=v,actor=user); assert v.status=="submitted" and artwork.status=="in_review"
    review_artwork_version(version=v,reviewer=staff,decision=ArtworkReview.Decision.APPROVED,notes="OK")
    assert v.status=="approved" and artwork.status=="approved" and v.reviews.count()==1


@pytest.mark.django_db
def test_third_party_content_requires_evidence():
    user=User.objects.create_user(username="artist",password="password123"); org=active_designer(user); artwork,v=complete_artwork(org,user)
    set_ip_declaration(version=v,actor=user,rights_basis=IPDeclaration.RightsBasis.NONEXCLUSIVE_LICENSE,rights_holder_name="Licensor",third_party_content=True,accepts_ip_policy=True)
    with pytest.raises(ValidationError): submit_artwork_version(version=v,actor=user)


@pytest.mark.django_db
def test_cross_tenant_artwork_create_product_blocked():
    a=User.objects.create_user(username="a",password="password123"); b=User.objects.create_user(username="b",password="password123"); orga=active_designer(a,"A"); orgb=active_designer(b,"B")
    art,v=complete_artwork(orga,a); v.status=ArtworkVersion.Status.APPROVED; v.save(); art.status=Artwork.Status.APPROVED; art.save(); garment,_=approved_garment(orgb,b)
    with pytest.raises(ValidationError): create_designed_product(organization=orga,actor=a,garment_version=garment,artwork_version=v,title="Bad")


@pytest.mark.django_db
def test_designed_product_requires_approved_inputs_and_placement():
    user=User.objects.create_user(username="artist",password="password123"); org=active_designer(user); art,v=complete_artwork(org,user); v.status=ArtworkVersion.Status.APPROVED; v.save(); art.status=Artwork.Status.APPROVED; art.save(); garment,zone=approved_garment(org,user)
    product=create_designed_product(organization=org,actor=user,garment_version=garment,artwork_version=v,title="Wave Tee")
    with pytest.raises(ValidationError): publish_designed_product(product=product,actor=user)
    add_product_placement(product=product,actor=user,decoration_zone=zone,transform={"x":0.5,"y":0.5,"scale":1},production_method="print")
    publish_designed_product(product=product,actor=user); assert product.status==DesignedProduct.Status.PUBLISHED


@pytest.mark.django_db
def test_ip_takedown_suspends_artwork_and_products():
    user=User.objects.create_user(username="artist",password="password123"); staff=User.objects.create_user(username="staff",password="password123",is_staff=True); org=active_designer(user); art,v=complete_artwork(org,user); v.status=ArtworkVersion.Status.APPROVED; v.save(); art.status=Artwork.Status.APPROVED; art.save(); garment,zone=approved_garment(org,user)
    product=create_designed_product(organization=org,actor=user,garment_version=garment,artwork_version=v,title="Wave Tee"); add_product_placement(product=product,actor=user,decoration_zone=zone,transform={},production_method="print"); publish_designed_product(product=product,actor=user)
    case=create_ip_case(actor=user,artwork=art,reporter_name="Claimant",reporter_email="c@example.com",claimant_rights="Copyright owner",allegation="Unauthorized use")
    moderate_ip_case(case=case,reviewer=staff,status=IPCase.Status.RESOLVED,resolution=IPCase.Resolution.TAKEDOWN,notes="Verified")
    art.refresh_from_db(); product.refresh_from_db(); assert art.status==Artwork.Status.SUSPENDED and product.status==DesignedProduct.Status.SUSPENDED


@pytest.mark.django_db
def test_ip_case_targets_exactly_one_entity():
    user=User.objects.create_user(username="artist",password="password123"); org=active_designer(user); art,_=complete_artwork(org,user)
    with pytest.raises(ValidationError): create_ip_case(actor=user,reporter_name="C",reporter_email="c@example.com",claimant_rights="rights",allegation="claim")
