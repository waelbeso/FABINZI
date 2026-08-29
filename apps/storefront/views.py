from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from apps.artwork.models import DesignedProduct
from apps.organizations.models import Membership, Organization
from .models import ProductVariant, StoreProduct, Storefront, StudioProject
from .services import create_store_product, create_storefront, create_studio_project, publish_store_product, publish_storefront, require_project_owner


def store_marketplace(request):
    return render(request,"storefront/store_marketplace.html",{"stores":Storefront.objects.filter(status=Storefront.Status.PUBLISHED)})


def public_storefront(request,slug):
    store=get_object_or_404(Storefront,slug=slug,status=Storefront.Status.PUBLISHED)
    return render(request,"storefront/storefront_detail.html",{"store":store,"products":store.products.filter(status=StoreProduct.Status.PUBLISHED)})


def public_product(request,store_slug,product_slug):
    product=get_object_or_404(StoreProduct.objects.select_related("storefront","designed_product"),storefront__slug=store_slug,storefront__status=Storefront.Status.PUBLISHED,slug=product_slug,status=StoreProduct.Status.PUBLISHED)
    return render(request,"storefront/product_detail.html",{"product":product})


@login_required
def designer_store_dashboard(request):
    membership=Membership.objects.filter(user=request.user,is_active=True,organization__kind=Organization.Kind.DESIGNER).select_related("organization").first()
    org=membership.organization if membership else None
    store=Storefront.objects.filter(organization=org).first() if org else None
    if request.method=="POST" and org and not store:
        store=create_storefront(organization=org,actor=request.user,slug=request.POST.get("slug",""),name_en=request.POST.get("name_en",""),name_ar=request.POST.get("name_ar",""),request=request)
        return redirect("designer-store")
    return render(request,"storefront/designer_store.html",{"organization":org,"store":store})


@login_required
def studio(request):
    projects=StudioProject.objects.filter(customer=request.user).select_related("product","variant")
    if request.method=="POST":
        product=get_object_or_404(StoreProduct,pk=request.POST.get("product")); variant=get_object_or_404(ProductVariant,pk=request.POST.get("variant")) if request.POST.get("variant") else None
        project=create_studio_project(customer=request.user,product=product,variant=variant,quantity=int(request.POST.get("quantity",1)),request=request)
        return redirect("studio-project",pk=project.pk)
    product=None
    if request.GET.get("product"):
        product=get_object_or_404(StoreProduct,pk=request.GET["product"],status=StoreProduct.Status.PUBLISHED,storefront__status=Storefront.Status.PUBLISHED)
    return render(request,"storefront/studio.html",{"projects":projects,"product":product})


@login_required
def studio_project(request,pk):
    project=get_object_or_404(StudioProject.objects.select_related("product","variant"),pk=pk); require_project_owner(request.user,project)
    return render(request,"storefront/studio_project.html",{"project":project})
