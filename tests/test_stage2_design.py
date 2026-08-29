import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError

from apps.design.models import DesignAsset, GarmentDesign, GarmentDesignVersion, SizeChartRow, TechnicalReview
from apps.design.services import add_asset, create_design, create_revision, review_version, submit_version
from apps.media.models import MediaAsset
from apps.organizations.models import Membership, Organization

User = get_user_model()


def active_designer(user, name="Studio"):
    org = Organization.objects.create(kind=Organization.Kind.DESIGNER, display_name=name, email=f"{name.lower()}@x.test", verification_status=Organization.VerificationStatus.ACTIVE, created_by=user)
    Membership.objects.create(organization=org, user=user, role=Membership.Role.OWNER)
    return org


@pytest.mark.django_db
def test_active_designer_can_create_design_and_version():
    user=User.objects.create_user(username="d",password="password123"); org=active_designer(user)
    design=create_design(organization=org,actor=user,title="Tee")
    assert design.versions.get().version_number == 1


@pytest.mark.django_db
def test_unapproved_designer_cannot_create_design():
    user=User.objects.create_user(username="d",password="password123"); org=Organization.objects.create(kind="designer",display_name="Draft",email="d@x.test",created_by=user); Membership.objects.create(organization=org,user=user,role="owner")
    with pytest.raises(ValidationError): create_design(organization=org,actor=user,title="Tee")


@pytest.mark.django_db
def test_cross_tenant_design_access_blocked():
    a=User.objects.create_user(username="a",password="password123"); b=User.objects.create_user(username="b",password="password123"); org=active_designer(a,"A"); design=create_design(organization=org,actor=a,title="Tee")
    with pytest.raises(PermissionDenied): create_revision(design=design,actor=b)


@pytest.mark.django_db
def test_technical_assets_private_and_submission_review_flow():
    user=User.objects.create_user(username="d",password="password123"); staff=User.objects.create_user(username="staff",password="password123",is_staff=True); org=active_designer(user); design=create_design(organization=org,actor=user,title="Tee"); v=design.versions.get(); v.base_material="Cotton"; v.technical_specs={"gsm":180}; v.save(); SizeChartRow.objects.create(version=v,size_label="M",measurements={"chest_cm":52})
    tech=MediaAsset.objects.create(provider="amazon_s3",provider_asset_id="tech.pdf",original_filename="tech.pdf",mime_type="application/pdf",size_bytes=10,access="private",uploaded_by=user)
    image=MediaAsset.objects.create(provider="cloudflare_images",provider_asset_id="img1",original_filename="tee.png",mime_type="image/png",size_bytes=10,access="public",uploaded_by=user)
    add_asset(version=v,actor=user,media_asset=tech,kind=DesignAsset.Kind.TECH_PACK); add_asset(version=v,actor=user,media_asset=image,kind=DesignAsset.Kind.PRODUCT_IMAGE)
    submit_version(version=v,actor=user); assert v.status == "submitted" and design.status == "in_review"
    review_version(version=v,reviewer=staff,decision=TechnicalReview.Decision.REVISION_REQUIRED,notes="Fix seam")
    assert v.status == "revision_required" and design.status == "revision_required" and v.reviews.count() == 1
    new=create_revision(design=design,actor=user); assert new.version_number == 2 and new.size_rows.count() == 1


@pytest.mark.django_db
def test_technical_file_cannot_be_public_or_cloudflare():
    user=User.objects.create_user(username="d",password="password123"); org=active_designer(user); v=create_design(organization=org,actor=user,title="Tee").versions.get()
    bad=MediaAsset.objects.create(provider="cloudflare_images",provider_asset_id="bad",original_filename="file.pdf",mime_type="application/pdf",size_bytes=1,access="public",uploaded_by=user)
    with pytest.raises(ValidationError): add_asset(version=v,actor=user,media_asset=bad,kind=DesignAsset.Kind.TECH_PACK)


@pytest.mark.django_db
def test_submitted_version_is_immutable():
    user=User.objects.create_user(username="d",password="password123"); org=active_designer(user); v=create_design(organization=org,actor=user,title="Tee").versions.get(); v.status=GarmentDesignVersion.Status.SUBMITTED; v.save()
    media=MediaAsset.objects.create(provider="amazon_s3",provider_asset_id="x",original_filename="x.pdf",mime_type="application/pdf",size_bytes=1,access="private",uploaded_by=user)
    with pytest.raises(ValidationError): add_asset(version=v,actor=user,media_asset=media,kind=DesignAsset.Kind.TECH_PACK)
