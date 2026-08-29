import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.artwork.models import Artwork, ArtworkVersion, DesignedProduct
from apps.design.models import DecorationZone, GarmentDesign, GarmentDesignVersion
from apps.media.models import MediaAsset
from apps.organizations.models import Membership, Organization
from apps.storefront.models import CustomizationElement, StoreProduct, Storefront, StudioProject
from apps.storefront.services import add_customization_element, add_product_image, add_variant, create_store_product, create_storefront, create_studio_project, enable_customization, mark_project_ready, publish_store_product, publish_storefront, update_studio_project

User=get_user_model()

def designer(user,name="Brand"):
    org=Organization.objects.create(kind="designer",display_name=name,email=f"{name.lower()}@x.test",verification_status="active",created_by=user); Membership.objects.create(organization=org,user=user,role="owner"); return org

def published_design(org,user):
    gd=GarmentDesign.objects.create(organization=org,title="Tee",status="approved",created_by=user); gv=GarmentDesignVersion.objects.create(design=gd,version_number=1,status="approved",created_by=user); zone=DecorationZone.objects.create(version=gv,name="Front",method="both",placement={"x":.5,"y":.5})
    art=Artwork.objects.create(organization=org,title="Wave",status="approved",created_by=user); av=ArtworkVersion.objects.create(artwork=art,version_number=1,status="approved",created_by=user)
    dp=DesignedProduct.objects.create(organization=org,garment_version=gv,artwork_version=av,title="Wave Tee",status="published",created_by=user)
    return dp,zone

def ready_store(owner):
    org=designer(owner); dp,zone=published_design(org,owner); store=create_storefront(organization=org,actor=owner,slug="brand",name_en="Brand"); publish_storefront(storefront=store,actor=owner)
    product=create_store_product(storefront=store,actor=owner,designed_product=dp,slug="wave-tee",title_en="Wave Tee",base_price="500.00",customization_enabled=True)
    variant=add_variant(product=product,actor=owner,sku="WT-M-BLK",size="M",color_name="Black",color_hex="#111111")
    image=MediaAsset.objects.create(provider="cloudflare_images",provider_asset_id="p1",original_filename="p.png",mime_type="image/png",size_bytes=2,access="public",uploaded_by=owner); add_product_image(product=product,actor=owner,media_asset=image); publish_store_product(product=product,actor=owner)
    return org,store,product,variant,zone

@pytest.mark.django_db
def test_published_store_and_product_are_public():
    owner=User.objects.create_user(username="owner",password="password123"); _,store,product,_,_=ready_store(owner); c=APIClient(); r=c.get(f"/api/v1/stores/{store.slug}/products/{product.slug}/"); assert r.status_code==200 and r.data["title_en"]=="Wave Tee"

@pytest.mark.django_db
def test_unpublished_product_not_public():
    owner=User.objects.create_user(username="owner",password="password123"); org=designer(owner); dp,_=published_design(org,owner); store=create_storefront(organization=org,actor=owner,slug="brand",name_en="Brand"); publish_storefront(storefront=store,actor=owner); product=create_store_product(storefront=store,actor=owner,designed_product=dp,slug="draft",title_en="Draft",base_price=10); c=APIClient(); assert c.get("/api/v1/stores/brand/products/draft/").status_code==404

@pytest.mark.django_db
def test_cross_tenant_designed_product_blocked():
    a=User.objects.create_user(username="a",password="password123"); b=User.objects.create_user(username="b",password="password123"); oa=designer(a,"A"); ob=designer(b,"B"); dp,_=published_design(ob,b); store=create_storefront(organization=oa,actor=a,slug="a",name_en="A")
    with pytest.raises(ValidationError): create_store_product(storefront=store,actor=a,designed_product=dp,slug="bad",title_en="Bad",base_price=1)

@pytest.mark.django_db
def test_customer_studio_project_customization_and_ready_lock():
    owner=User.objects.create_user(username="owner",password="password123"); customer=User.objects.create_user(username="customer",password="password123"); _,_,product,variant,zone=ready_store(owner); p=create_studio_project(customer=customer,product=product,variant=variant,quantity=2); c=enable_customization(project=p,actor=customer); e=add_customization_element(customization=c,actor=customer,decoration_zone=zone,kind=CustomizationElement.Kind.TEXT,text="WAEL",transform={"x":.5,"y":.5}); assert e.pk; mark_project_ready(project=p,actor=customer); assert p.status==StudioProject.Status.READY
    with pytest.raises(ValidationError): update_studio_project(project=p,actor=customer,quantity=3)

@pytest.mark.django_db
def test_studio_project_is_private_to_customer():
    owner=User.objects.create_user(username="owner",password="password123"); customer=User.objects.create_user(username="customer",password="password123"); intruder=User.objects.create_user(username="intruder",password="password123"); _,_,product,variant,_=ready_store(owner); p=create_studio_project(customer=customer,product=product,variant=variant)
    with pytest.raises(PermissionDenied): update_studio_project(project=p,actor=intruder,quantity=2)

@pytest.mark.django_db
def test_customization_zone_must_match_product_garment():
    owner=User.objects.create_user(username="owner",password="password123"); customer=User.objects.create_user(username="customer",password="password123"); other=User.objects.create_user(username="other",password="password123"); _,_,product,variant,_=ready_store(owner); other_org=designer(other,"Other"); _,wrong_zone=published_design(other_org,other); p=create_studio_project(customer=customer,product=product,variant=variant); c=enable_customization(project=p,actor=customer)
    with pytest.raises(ValidationError): add_customization_element(customization=c,actor=customer,decoration_zone=wrong_zone,kind="text",text="X")

@pytest.mark.django_db
def test_stock_mode_enforces_quantity_without_reserving_stock():
    owner=User.objects.create_user(username="owner",password="password123"); customer=User.objects.create_user(username="customer",password="password123"); _,_,product,variant,_=ready_store(owner); product.fulfillment_mode="stock"; product.save(); variant.stock_quantity=2; variant.save()
    with pytest.raises(ValidationError): create_studio_project(customer=customer,product=product,variant=variant,quantity=3)
    assert variant.stock_quantity==2
