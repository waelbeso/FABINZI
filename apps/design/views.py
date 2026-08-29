from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from apps.organizations.models import Membership, Organization
from .forms import GarmentDesignForm, GarmentDesignVersionForm
from .models import GarmentDesign
from .services import DESIGN_EDIT_ROLES, create_design, require_design_access


@login_required
def design_list(request):
    memberships = Membership.objects.filter(user=request.user, is_active=True, organization__kind=Organization.Kind.DESIGNER).select_related("organization")
    designs = GarmentDesign.objects.filter(organization__memberships__user=request.user, organization__memberships__is_active=True).distinct()
    if request.method == "POST":
        form = GarmentDesignForm(request.POST)
        org = get_object_or_404(Organization, pk=request.POST.get("organization"))
        if form.is_valid():
            design = create_design(organization=org, actor=request.user, request=request, **form.cleaned_data)
            return redirect("designer-design-detail", pk=design.pk)
    else: form = GarmentDesignForm()
    return render(request, "design/design_list.html", {"designs": designs, "memberships": memberships, "form": form})


@login_required
def design_detail(request, pk):
    design = get_object_or_404(GarmentDesign, pk=pk); require_design_access(request.user, design)
    version = design.versions.order_by("-version_number").first()
    form = GarmentDesignVersionForm(instance=version)
    if request.method == "POST":
        require_design_access(request.user, design, edit=True)
        if version.status != version.Status.DRAFT: raise PermissionDenied("Reviewed versions are immutable.")
        form = GarmentDesignVersionForm(request.POST, instance=version)
        if form.is_valid(): form.save(); return redirect("designer-design-detail", pk=design.pk)
    return render(request, "design/design_detail.html", {"design": design, "version": version, "form": form})
