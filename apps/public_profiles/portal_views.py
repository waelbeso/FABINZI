from copy import deepcopy

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import redirect, render

from apps.media.manufacturer_public_services import create_manufacturer_public_image, manufacturer_public_image_eligible, validate_public_image
from apps.media.models import MediaAsset
from apps.organizations.designer_context import DESIGNER_MANAGE_ROLES, require_active_designer_context
from apps.organizations.manufacturer_context import MANUFACTURER_MANAGE_ROLES, require_active_manufacturer_context
from apps.organizations.models import Organization, PublicProfileRevision
from apps.organizations.public_profile_services import normalize_public_profile_data, current_public_profile_data, save_public_profile_revision, submit_public_profile_revision
from .services import approved_manufacturer_products, ensure_public_state, hide_public_profile, request_public_profile_visibility, verified_canonical_capabilities


def _error(exc):
    return "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)


def _list(value):
    return [item.strip() for item in str(value or "").replace("\n", ",").split(",") if item.strip()]


def _public_images(organization):
    user_ids = organization.memberships.filter(is_active=True).values_list("user_id", flat=True)
    if organization.kind == Organization.Kind.MANUFACTURER:
        assets = MediaAsset.objects.filter(access=MediaAsset.Access.PUBLIC, mime_type__startswith="image/").filter(Q(metadata__organization_id=organization.pk) | Q(metadata__organization_id=str(organization.pk)) | Q(uploaded_by_id__in=user_ids)).order_by("-created_at")
        return [asset for asset in assets if manufacturer_public_image_eligible(asset, organization)]
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
    if manufacturer:
        uploads = {purpose: request.FILES.get(f"{purpose}_image_upload") for purpose in ("profile", "cover")}
        if any(uploads.values()):
            if organization.public_profile_revisions.filter(status__in=[PublicProfileRevision.Status.SUBMITTED, PublicProfileRevision.Status.UNDER_REVIEW]).exists():
                raise ValidationError("A revision is already under review. / توجد مراجعة قيد المراجعة بالفعل.")
            for purpose, upload in uploads.items():
                if upload:
                    payload["public_state"][f"{purpose}_image_id"] = None
            payload = normalize_public_profile_data(organization=organization, proposed_data=payload)
            for upload in uploads.values():
                if upload:
                    validate_public_image(upload)
                    upload.seek(0)
            for purpose, upload in uploads.items():
                if upload:
                    asset = create_manufacturer_public_image(upload=upload, organization=organization, actor=request.user, purpose=purpose, request=request)
                    payload["public_state"][f"{purpose}_image_id"] = asset.pk
    revision = save_public_profile_revision(organization=organization, actor=request.user, proposed_data=payload, request=request)
    if action == "submit_revision":
        submit_public_profile_revision(revision=revision, actor=request.user, request=request)
        return "Public profile revision submitted for FABINZI review."
    return "Public profile draft saved."


def _legacy_designer_profile_data(organization):
    """Render legacy Designer data safely without weakening save-time validation."""

    state = ensure_public_state(organization)
    profile = organization.designer_profile
    social_links = deepcopy(profile.social_links or {})
    instagram = str(social_links.get("instagram") or "").strip()
    if instagram.startswith("@") and len(instagram) > 1:
        social_links["instagram"] = f"https://www.instagram.com/{instagram[1:].strip('/')}/"

    return {
        "organization": {
            "display_name": organization.display_name,
            "website": organization.website,
            "city": organization.city,
            "region": organization.region,
            "country": organization.country,
        },
        "public_state": {
            "public_name_en": state.public_name_en or organization.display_name,
            "public_name_ar": state.public_name_ar,
            "bio_en": state.bio_en,
            "bio_ar": state.bio_ar,
            "specializations": list(state.specializations or []),
            "profile_image_id": state.profile_image_id,
            "cover_image_id": state.cover_image_id,
            "public_google_maps_url": state.public_google_maps_url,
            "public_categories": list(state.public_categories or []),
            "public_certifications": list(state.public_certifications or []),
        },
        "profile": {
            "studio_name": profile.studio_name,
            "portfolio_url": profile.portfolio_url,
            "social_links": social_links,
        },
    }


def _profile_context(organization, *, tolerate_legacy_designer_data=False):
    latest = organization.public_profile_revisions.order_by("-created_at").first()
    editable = organization.public_profile_revisions.filter(status__in=PublicProfileRevision.EDITABLE_STATUSES).first()
    try:
        current = current_public_profile_data(organization)
    except ValidationError:
        if not tolerate_legacy_designer_data:
            raise
        current = _legacy_designer_profile_data(organization)
    return latest, deepcopy(editable.proposed_data if editable else current), current


def _manufacturer_portal_state(organization, *, requested_edit=False, attempted_data=None, error=""):
    revision, edit_data, current = _profile_context(organization)
    locked = bool(
        revision
        and revision.status in {
            PublicProfileRevision.Status.SUBMITTED,
            PublicProfileRevision.Status.UNDER_REVIEW,
        }
    )
    edit_mode = bool(requested_edit and not locked)
    if attempted_data is not None:
        edit_data = attempted_data
        edit_mode = True
    proposed = deepcopy(revision.proposed_data) if revision else None
    return {
        "current_public_data": current,
        "edit_public_data": edit_data,
        "public_revision": revision,
        "public_revision_data": proposed,
        "public_profile_edit_mode": edit_mode,
        "public_profile_edit_locked": locked,
        "public_profile_error": error,
        "public_images": _public_images(organization) if edit_mode else [],
    }


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
    revision, edit_data, current = _profile_context(organization, tolerate_legacy_designer_data=True)
    context.update({"public_state": state, "current_public_data": current, "edit_public_data": edit_data, "public_revision": revision, "public_images": _public_images(organization)})
    return render(request, "public_profiles/designer_portal.html", context)


@login_required
def manufacturer_public_profile(request):
    context = require_active_manufacturer_context(request, roles=MANUFACTURER_MANAGE_ROLES)
    organization = context["manufacturer_organization"]
    state = ensure_public_state(organization)
    requested_edit = request.GET.get("edit") == "1" or request.method == "POST"

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action not in {"save_revision", "submit_revision", "hide", "request_visibility"}:
            messages.error(request, "Unsupported public-profile action.")
            return redirect(f"/manufacturer/public-profile/?org={organization.pk}")
        if action in {"hide", "request_visibility"}:
            try:
                result = _profile_action(request, organization, manufacturer=True)
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _error(exc))
            else:
                messages.success(request, result)
            return redirect(f"/manufacturer/public-profile/?org={organization.pk}")

        locked = organization.public_profile_revisions.filter(
            status__in=[PublicProfileRevision.Status.SUBMITTED, PublicProfileRevision.Status.UNDER_REVIEW]
        ).exists()
        if locked:
            messages.error(request, "A public profile revision is already submitted or under FABINZI review.")
            return redirect(f"/manufacturer/public-profile/?org={organization.pk}")
        try:
            result = _profile_action(request, organization, manufacturer=True)
        except (ValidationError, PermissionDenied) as exc:
            _revision, attempted = _editable_payload(organization)
            attempted = _apply_post(attempted, request.POST, manufacturer=True)
            context.update(
                _manufacturer_portal_state(
                    organization,
                    requested_edit=True,
                    attempted_data=attempted,
                    error=_error(exc),
                )
            )
            context.update({"public_state": state, "verified_capabilities": verified_canonical_capabilities(organization)})
            return render(request, "public_profiles/manufacturer_portal.html", context)
        messages.success(request, result)
        if action == "save_revision":
            return redirect(f"/manufacturer/public-profile/?org={organization.pk}&edit=1")
        return redirect(f"/manufacturer/public-profile/?org={organization.pk}")

    context.update(_manufacturer_portal_state(organization, requested_edit=requested_edit))
    context.update({"public_state": state, "verified_capabilities": verified_canonical_capabilities(organization)})
    return render(request, "public_profiles/manufacturer_portal.html", context)


@login_required
def manufacturer_public_products(request):
    context = require_active_manufacturer_context(request, roles=MANUFACTURER_MANAGE_ROLES)
    organization = context["manufacturer_organization"]
    context["public_product_approvals"] = approved_manufacturer_products(organization)
    return render(request, "public_profiles/manufacturer_products_portal.html", context)
