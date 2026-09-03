from copy import deepcopy

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit_event
from apps.media.models import MediaAsset
from .models import Membership, Organization, PublicProfileRevision
from .services import require_org_access


DESIGNER_PUBLIC_ORGANIZATION_FIELDS = {
    "display_name",
    "website",
    "city",
    "region",
    "country",
}
DESIGNER_PUBLIC_PROFILE_FIELDS = {
    "studio_name",
    "portfolio_url",
    "social_links",
}
MANUFACTURER_PUBLIC_ORGANIZATION_FIELDS = {
    "display_name",
    "website",
    "city",
    "region",
    "country",
}
MANUFACTURER_PUBLIC_LISTING_FIELDS = {
    "headline_en",
    "headline_ar",
    "overview_en",
    "overview_ar",
}
PUBLIC_STATE_FIELDS = {
    "public_name_en",
    "public_name_ar",
    "bio_en",
    "bio_ar",
    "specializations",
    "profile_image_id",
    "cover_image_id",
    "public_google_maps_url",
    "public_categories",
    "public_certifications",
}
PUBLIC_SOCIAL_KEYS = {"instagram", "behance", "linkedin"}

_url_validator = URLValidator(schemes=["http", "https"])


def _validate_optional_url(value, *, field_name):
    value = str(value or "").strip()
    if value:
        try:
            _url_validator(value)
        except ValidationError as exc:
            raise ValidationError({field_name: "Enter a valid http(s) URL."}) from exc
    return value


def _clean_public_organization(data):
    cleaned = {
        "display_name": str(data.get("display_name") or "").strip(),
        "website": _validate_optional_url(data.get("website"), field_name="website"),
        "city": str(data.get("city") or "").strip(),
        "region": str(data.get("region") or "").strip(),
        "country": str(data.get("country") or "EG").strip().upper(),
    }
    if not cleaned["display_name"]:
        raise ValidationError({"display_name": "A public display name is required."})
    if len(cleaned["display_name"]) > 180:
        raise ValidationError({"display_name": "Public display name is too long."})
    if len(cleaned["city"]) > 120 or len(cleaned["region"]) > 120:
        raise ValidationError("Public city/region is too long.")
    if len(cleaned["country"]) != 2:
        raise ValidationError({"country": "Use a two-letter country code."})
    return cleaned


def _clean_designer_profile(data):
    social_links = {}
    raw_links = data.get("social_links") or {}
    if not isinstance(raw_links, dict):
        raise ValidationError({"social_links": "Public social links must be a key/value object."})
    for key in PUBLIC_SOCIAL_KEYS:
        value = _validate_optional_url(raw_links.get(key), field_name=key)
        if value:
            social_links[key] = value
    studio_name = str(data.get("studio_name") or "").strip()
    if len(studio_name) > 180:
        raise ValidationError({"studio_name": "Studio name is too long."})
    return {
        "studio_name": studio_name,
        "portfolio_url": _validate_optional_url(
            data.get("portfolio_url"), field_name="portfolio_url"
        ),
        "social_links": social_links,
    }


def _clean_public_list(value, *, field_name, limit=24):
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValidationError({field_name: "Use a list of public values."})
    result = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text[:120])
        if len(result) >= limit:
            break
    return result


def _clean_public_media_id(value, *, field_name):
    if value in (None, "", 0, "0"):
        return None
    try:
        asset_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({field_name: "Choose a valid public image."}) from exc
    asset = MediaAsset.objects.filter(pk=asset_id).first()
    if not asset or asset.access != MediaAsset.Access.PUBLIC or not asset.mime_type.startswith("image/"):
        raise ValidationError({field_name: "Choose an explicitly PUBLIC image MediaAsset."})
    return asset_id


def _clean_public_state(data, *, organization):
    if not isinstance(data, dict):
        raise ValidationError({"public_state": "Public profile state data must be an object."})
    name_en = str(data.get("public_name_en") or organization.display_name or "").strip()
    name_ar = str(data.get("public_name_ar") or "").strip()
    if not name_en and not name_ar:
        raise ValidationError("At least one public professional name is required.")
    return {
        "public_name_en": name_en[:180],
        "public_name_ar": name_ar[:180],
        "bio_en": str(data.get("bio_en") or "").strip()[:5000],
        "bio_ar": str(data.get("bio_ar") or "").strip()[:5000],
        "specializations": _clean_public_list(
            data.get("specializations"), field_name="specializations"
        ),
        "profile_image_id": _clean_public_media_id(
            data.get("profile_image_id"), field_name="profile_image_id"
        ),
        "cover_image_id": _clean_public_media_id(
            data.get("cover_image_id"), field_name="cover_image_id"
        ),
        "public_google_maps_url": _validate_optional_url(
            data.get("public_google_maps_url"), field_name="public_google_maps_url"
        ),
        "public_categories": _clean_public_list(
            data.get("public_categories"), field_name="public_categories"
        ),
        "public_certifications": _clean_public_list(
            data.get("public_certifications"), field_name="public_certifications"
        ),
    }


def _clean_manufacturer_listing(data):
    if not isinstance(data, dict):
        raise ValidationError({"listing": "Public Manufacturer listing data must be an object."})
    return {
        "headline_en": str(data.get("headline_en") or "").strip()[:180],
        "headline_ar": str(data.get("headline_ar") or "").strip()[:180],
        "overview_en": str(data.get("overview_en") or "").strip()[:5000],
        "overview_ar": str(data.get("overview_ar") or "").strip()[:5000],
    }


def normalize_public_profile_data(*, organization, proposed_data):
    if not isinstance(proposed_data, dict):
        raise ValidationError("Public profile revision data must be an object.")
    organization_data = proposed_data.get("organization") or {}
    if not isinstance(organization_data, dict):
        raise ValidationError({"organization": "Public organization data must be an object."})
    cleaned = {
        "organization": _clean_public_organization(organization_data),
        "public_state": _clean_public_state(
            proposed_data.get("public_state") or {}, organization=organization
        ),
    }
    if organization.kind == Organization.Kind.DESIGNER:
        profile_data = proposed_data.get("profile") or {}
        if not isinstance(profile_data, dict):
            raise ValidationError({"profile": "Public Designer profile data must be an object."})
        cleaned["profile"] = _clean_designer_profile(profile_data)
    elif organization.kind == Organization.Kind.MANUFACTURER:
        cleaned["listing"] = _clean_manufacturer_listing(proposed_data.get("listing") or {})
    else:
        raise ValidationError("Public profile revisions require a professional organization.")
    return cleaned


def _public_state_data(organization):
    try:
        state = organization.public_state
    except Exception:
        state = None
    if not state:
        return {
            "public_name_en": organization.display_name,
            "public_name_ar": "",
            "bio_en": "",
            "bio_ar": "",
            "specializations": [],
            "profile_image_id": None,
            "cover_image_id": None,
            "public_google_maps_url": "",
            "public_categories": [],
            "public_certifications": [],
        }
    return {
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
    }


def current_public_profile_data(organization):
    organization_data = {
        "display_name": organization.display_name,
        "website": organization.website,
        "city": organization.city,
        "region": organization.region,
        "country": organization.country,
    }
    payload = {
        "organization": organization_data,
        "public_state": _public_state_data(organization),
    }
    if organization.kind == Organization.Kind.DESIGNER:
        profile = organization.designer_profile
        payload["profile"] = {
            "studio_name": profile.studio_name,
            "portfolio_url": profile.portfolio_url,
            "social_links": deepcopy(profile.social_links or {}),
        }
    elif organization.kind == Organization.Kind.MANUFACTURER:
        try:
            listing = organization.marketplace_listing
        except Exception:
            listing = None
        payload["listing"] = {
            "headline_en": listing.headline_en if listing else "",
            "headline_ar": listing.headline_ar if listing else "",
            "overview_en": listing.overview_en if listing else "",
            "overview_ar": listing.overview_ar if listing else "",
        }
    return normalize_public_profile_data(
        organization=organization,
        proposed_data=payload,
    )


def _require_professional_profile_manager(actor, organization):
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise ValidationError(
            "Only an approved active professional organization may propose public profile changes."
        )
    require_org_access(
        actor,
        organization,
        roles=[Membership.Role.OWNER, Membership.Role.MANAGER],
    )


@transaction.atomic
def save_public_profile_revision(*, organization, actor, proposed_data, request=None):
    _require_professional_profile_manager(actor, organization)
    cleaned = normalize_public_profile_data(
        organization=organization,
        proposed_data=proposed_data,
    )
    locked = organization.public_profile_revisions.filter(
        status__in=[
            PublicProfileRevision.Status.SUBMITTED,
            PublicProfileRevision.Status.UNDER_REVIEW,
        ]
    ).first()
    if locked:
        if locked.proposed_data == cleaned:
            return locked
        raise ValidationError(
            "A public profile revision is already submitted or under FABINZI review."
        )

    revision = organization.public_profile_revisions.filter(
        status__in=PublicProfileRevision.EDITABLE_STATUSES
    ).first()
    created = revision is None
    if created:
        revision = PublicProfileRevision(organization=organization, created_by=actor)
    revision.proposed_data = cleaned
    revision.full_clean()
    revision.save()
    record_audit_event(
        actor=actor,
        action=(
            "public_profile.revision.draft_saved"
            if created
            else "public_profile.revision.updated"
        ),
        instance=revision,
        metadata={"organization_id": organization.pk, "status": revision.status},
        request=request,
    )
    return revision


@transaction.atomic
def submit_public_profile_revision(
    *, revision, actor, request=None, allow_unchanged_for_visibility=False
):
    _require_professional_profile_manager(actor, revision.organization)
    if revision.status == PublicProfileRevision.Status.SUBMITTED:
        return revision
    if revision.status not in PublicProfileRevision.EDITABLE_STATUSES:
        raise ValidationError(
            "Only a draft or changes-required public profile revision can be submitted."
        )
    normalized = normalize_public_profile_data(
        organization=revision.organization,
        proposed_data=revision.proposed_data,
    )
    if (
        normalized == current_public_profile_data(revision.organization)
        and not allow_unchanged_for_visibility
    ):
        raise ValidationError("There are no public profile changes to submit.")
    previous_status = revision.status
    revision.proposed_data = normalized
    revision.status = PublicProfileRevision.Status.SUBMITTED
    revision.submitted_at = timezone.now()
    revision.reviewed_at = None
    revision.reviewed_by = None
    revision.review_notes = ""
    revision.save(
        update_fields=[
            "proposed_data",
            "status",
            "submitted_at",
            "reviewed_at",
            "reviewed_by",
            "review_notes",
            "updated_at",
        ]
    )
    record_audit_event(
        actor=actor,
        action="public_profile.revision.submitted",
        instance=revision,
        metadata={
            "organization_id": revision.organization_id,
            "previous_status": previous_status,
            "visibility_only": bool(allow_unchanged_for_visibility),
        },
        request=request,
    )
    return revision


@transaction.atomic
def propose_and_submit_public_profile_update(
    *, organization, actor, proposed_data, request=None
):
    cleaned = normalize_public_profile_data(
        organization=organization,
        proposed_data=proposed_data,
    )
    current = current_public_profile_data(organization)
    if cleaned == current:
        return organization.public_profile_revisions.filter(
            status__in=PublicProfileRevision.OPEN_STATUSES
        ).first()
    revision = save_public_profile_revision(
        organization=organization,
        actor=actor,
        proposed_data=cleaned,
        request=request,
    )
    if revision.status in PublicProfileRevision.EDITABLE_STATUSES:
        revision = submit_public_profile_revision(
            revision=revision,
            actor=actor,
            request=request,
        )
    return revision


def _apply_approved_public_data(revision):
    from apps.manufacturer_marketplace.models import ManufacturerListing
    from apps.public_profiles.models import ProfessionalPublicState
    from apps.public_profiles.services import ensure_public_state

    organization = revision.organization
    payload = normalize_public_profile_data(
        organization=organization,
        proposed_data=revision.proposed_data,
    )
    for field in (
        DESIGNER_PUBLIC_ORGANIZATION_FIELDS
        if organization.kind == Organization.Kind.DESIGNER
        else MANUFACTURER_PUBLIC_ORGANIZATION_FIELDS
    ):
        if field in payload["organization"]:
            setattr(organization, field, payload["organization"][field])
    organization.full_clean(exclude=["created_by"])
    organization.save()

    if organization.kind == Organization.Kind.DESIGNER:
        profile = organization.designer_profile
        for field in DESIGNER_PUBLIC_PROFILE_FIELDS:
            if field in payload["profile"]:
                setattr(profile, field, payload["profile"][field])
        profile.full_clean()
        profile.save()
    else:
        listing, _ = ManufacturerListing.objects.get_or_create(organization=organization)
        for field in MANUFACTURER_PUBLIC_LISTING_FIELDS:
            setattr(listing, field, payload["listing"][field])
        listing.full_clean()
        listing.save()

    state = ensure_public_state(organization)
    for field in PUBLIC_STATE_FIELDS:
        setattr(state, field, payload["public_state"][field])
    state.full_clean()
    state.save()
    return state


@transaction.atomic
def start_public_profile_review(*, revision, reviewer, request=None):
    if not reviewer.is_staff:
        raise PermissionDenied("Staff access required.")
    if revision.status == PublicProfileRevision.Status.UNDER_REVIEW:
        return revision
    if revision.status != PublicProfileRevision.Status.SUBMITTED:
        raise ValidationError("Only a submitted public profile revision can enter review.")
    revision.status = PublicProfileRevision.Status.UNDER_REVIEW
    revision.reviewed_by = reviewer
    revision.reviewed_at = None
    revision.review_notes = ""
    revision.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "review_notes",
            "updated_at",
        ]
    )
    record_audit_event(
        actor=reviewer,
        action="public_profile.revision.review_started",
        instance=revision,
        metadata={"organization_id": revision.organization_id},
        request=request,
    )
    return revision


@transaction.atomic
def review_public_profile_revision(
    *, revision, reviewer, decision, notes="", request=None
):
    from apps.public_profiles.models import ProfessionalPublicState

    if not reviewer.is_staff:
        raise PermissionDenied("Staff access required.")
    if decision not in {
        PublicProfileRevision.Status.APPROVED,
        PublicProfileRevision.Status.CHANGES_REQUIRED,
        PublicProfileRevision.Status.REJECTED,
    }:
        raise ValidationError("Unsupported public profile review decision.")
    if revision.status != PublicProfileRevision.Status.UNDER_REVIEW:
        raise ValidationError(
            "Only public profile revisions under review can receive a decision."
        )
    if (
        decision == PublicProfileRevision.Status.APPROVED
        and revision.organization.verification_status
        != Organization.VerificationStatus.ACTIVE
    ):
        raise ValidationError(
            "A suspended or inactive professional organization cannot publish a profile revision."
        )

    state = None
    if decision == PublicProfileRevision.Status.APPROVED:
        state = _apply_approved_public_data(revision)
        if state.visibility == ProfessionalPublicState.Visibility.PENDING_APPROVAL:
            state.visibility = ProfessionalPublicState.Visibility.VISIBLE
            state.save(update_fields=["visibility", "updated_at"])
    elif decision == PublicProfileRevision.Status.REJECTED:
        try:
            state = revision.organization.public_state
        except ProfessionalPublicState.DoesNotExist:
            state = None
        if state and state.visibility == ProfessionalPublicState.Visibility.PENDING_APPROVAL:
            state.visibility = ProfessionalPublicState.Visibility.HIDDEN
            state.save(update_fields=["visibility", "updated_at"])

    review_notes = str(notes or "").strip()
    revision.status = decision
    revision.review_notes = review_notes
    revision.reviewed_by = reviewer
    revision.reviewed_at = timezone.now()
    revision.save(
        update_fields=[
            "status",
            "review_notes",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        ]
    )
    record_audit_event(
        actor=reviewer,
        action=f"public_profile.revision.{decision}",
        instance=revision,
        metadata={
            "organization_id": revision.organization_id,
            "notes_present": bool(review_notes),
            "review_notes": review_notes,
            "public_visibility": state.visibility if state else None,
        },
        request=request,
    )
    return revision
