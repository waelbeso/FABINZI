from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.organizations.models import Membership, Organization
from .forms import ArtworkForm, ArtworkVersionForm, DesignedProductForm
from .models import Artwork, DesignedProduct
from .services import create_artwork, create_designed_product, require_artwork_access


def artwork_marketplace(request):
    artworks = Artwork.objects.filter(status=Artwork.Status.APPROVED).select_related("organization")
    return render(request, "artwork/marketplace.html", {"artworks": artworks})


@login_required
def designer_artworks(request):
    memberships = Membership.objects.filter(user=request.user, is_active=True, organization__kind=Organization.Kind.DESIGNER).select_related("organization")
    artworks = Artwork.objects.filter(organization__memberships__user=request.user, organization__memberships__is_active=True).distinct()
    form = ArtworkForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        org = get_object_or_404(Organization, pk=request.POST.get("organization"))
        artwork = create_artwork(organization=org, actor=request.user, request=request, **form.cleaned_data)
        return redirect("designer-artwork-detail", pk=artwork.pk)
    return render(request, "artwork/designer_artworks.html", {"memberships":memberships,"artworks":artworks,"form":form})


@login_required
def designer_artwork_detail(request, pk):
    artwork = get_object_or_404(Artwork, pk=pk); require_artwork_access(request.user, artwork)
    version = artwork.versions.order_by("-version_number").first(); form = ArtworkVersionForm(request.POST or None, instance=version)
    if request.method == "POST":
        require_artwork_access(request.user, artwork, edit=True)
        if version.status != version.Status.DRAFT:
            return render(request, "artwork/designer_artwork_detail.html", {"artwork":artwork,"version":version,"form":form,"locked":True}, status=409)
        if form.is_valid(): form.save(); return redirect("designer-artwork-detail", pk=artwork.pk)
    return render(request, "artwork/designer_artwork_detail.html", {"artwork":artwork,"version":version,"form":form})


@login_required
def designer_products(request):
    memberships = Membership.objects.filter(user=request.user, is_active=True, organization__kind=Organization.Kind.DESIGNER).select_related("organization")
    products = DesignedProduct.objects.filter(organization__memberships__user=request.user, organization__memberships__is_active=True).distinct()
    form = DesignedProductForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        org = get_object_or_404(Organization, pk=request.POST.get("organization"))
        product = create_designed_product(organization=org, actor=request.user, request=request, **form.cleaned_data)
        return redirect("designer-products")
    return render(request, "artwork/designer_products.html", {"memberships":memberships,"products":products,"form":form})
