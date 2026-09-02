from copy import deepcopy

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render

from apps.media.models import MediaAsset
from apps.organizations.designer_context import DESIGNER_MANAGE_ROLES, require_active_designer_context
from apps.organizations.manufacturer_context import MANUFACTURER_MANAGE_ROLES, require_active_manufacturer_context
from apps.organizations.models import PublicProfileRevision
from apps.organizations.public_profile_services import current_public_profile_data, save_public_profile_revision, submit_public_profile_revision
from .services import approved_manufacturer_products, ensure_public_state, hide_public_profile, request_public_profile_visibility, verified_canonical_capabilities


def _error(exc):
    return "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)


def _list(value):
    return [item.strip() for item in str(value or "").replace("\n", ",").split(",") if item.strip()]


def _public_images(organization):
    user_ids = organization.memberships.filter(is_active=True).values_list("user_id", flat=True)
    return MediaAsset.objects.filter(access=MediaAsset.Access.PUBLIC, mime_type__startswith="image/", uploaded_by_id__in=user_ids).order_by("-created_at")[:80]


def _editable_payload(organization):
    revision = organization.public_profile_revisions.filter(status__in=PublicProfileRevision.EDITABLE_STATUSES).first()
    return revision, deepcopy(revision.proposed_data if revision else current_public_profile_data(organization))


def _apply_post(payload, post, *, manufacturer=False):
    payload["public_state"].update({
        "public_name_en": post.get("public_name_en", ""),
        "public_name_ar": post.get("public_name_ar", ""),
        "bio_en": post.get("bio_en", ""),
        "bio_ar": post.get("bio_ar", ""),
        "specializations": _list(post.get("specializations")),
        "profile_image_id": post.get("profile_image_id") or None,
        "cover_image_id": post.get("cover_image_id") or None,
        "public_google_maps_url": post.get("public_google_maps_url", ""),
        "public_categories": _list(post.get("public_categories")),
        "public_certifications": _list(post.get("public_certifications")),
    })
    payload["organization"].update({
        "display_name": post.get("display_name", payload["organization"].get("display_name", "")),
        "website": post.get("website", ""),
        "city": post.get("city", ""),
        "region": post.get("region", ""),
        "country": post.get("country", "EG"),
    })
    if manufacturer:
        payload["listing"].update({"headline_en": post.get("headline_en", ""), "headline_ar": post.get("headline_ar", ""), "overview_en": post.get("overview_en", ""), "overview_ar": post.get("overview_ar", "")})
    else:
        payload["profile"].update({
            "studio_name": post.get("studio_name", ""),
            "portfolio_url": post.get("portfolio_url", ""),
            "social_links": {key: post.get(f"social_{key}", "") for key in ("instagram", "behance", "linkedin") if post.get(f"social_{key}", "").strip()},
        })
    return payload


def _profile_action(request, organization, *, manufacturer=False):
    action = request.POST.get("action")
    if action == "hide":
        hide_public_profile(organization=organization, actor=request.user, request=request)
        return "Public profile hidden immediately."
    if action == "request_visibility":
        request_public_profile_visibility(organization=organization, actor=request.user, request=request)
        return "Public visibility request submitted for FABINZI approval."
    _revision, payload = _editable_payload(organization)
    payload = _apply_post(payload, request.POST, manufacturer=manufacturer)
    revision = save_public_profile_revision(organization=organization, actor=request.user, proposed_data=payload, request=request)
    if action == "submit_revision":
        submit_public_profile_revision(revision=revision, actor=request.user, request=request)
        return "Public profile revision submitted for FABINZI review."
    return "Public profile draft saved."


def _profile_context(organization):
    latest = organization.public_profile_revisions.order_by("-created_at").first()
    editable = organization.public_profile_revisions.filter(status__in=PublicProfileRevision.EDITABLE_STATUSES).first()
    current = current_public_profile_data(organization)
    return latest, deepcopy(editable.proposed_data if editable else current), current


@login_required
def designer_public_profile(request):
    context = require_active_designer_context(request, roles=DESIGNER_MANAGE_ROLES)
    organization = context["designer_organization"]
    state = ensure_public_state(organization)
    if request.method == "POST":
        try:
            messages.success(request, _profile_action(request, organization, manufacturer=False))
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error(exc))
        return redirect(f"/designer/public-profile/?org={organization.pk}")
    revision, edit_data, current = _profile_context(organization)
    context.update({"public_state": state, "current_public_data": current, "edit_public_data": edit_data, "public_revision": revision, "public_images": _public_images(organization)})
    return render(request, "public_profiles/designer_portal.html", context)


@login_required
def manufacturer_public_profile(request):
    context = require_active_manufacturer_context(request, roles=MANUFACTURER_MANAGE_ROLES)
    organization = context["manufacturer_organization"]
    state = ensure_public_state(organization)
    if request.method == "POST":
        try:
            messages.success(request, _profile_action(request, organization, manufacturer=True))
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error(exc))
        return redirect(f"/manufacturer/public-profile/?org={organization.pk}")
    revision, edit_data, current = _profile_context(organization)
    context.update({"public_state": state, "current_public_data": current, "edit_public_data": edit_data, "public_revision": revision, "public_images": _public_images(organization), "verified_capabilities": verified_canonical_capabilities(organization)})
    return render(request, "public_profiles/manufacturer_portal.html", context)


@login_required
def manufacturer_public_products(request):
    context = require_active_manufacturer_context(request, roles=MANUFACTURER_MANAGE_ROLES)
    organization = context["manufacturer_organization"]
    context["public_product_approvals"] = approved_manufacturer_products(organization)
    return render(request, "public_profiles/manufacturer_products_portal.html", context)
