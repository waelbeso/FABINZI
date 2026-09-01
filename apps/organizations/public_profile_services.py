from copy import deepcopy

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit_event
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


def normalize_public_profile_data(*, organization, proposed_data):
    if not isinstance(proposed_data, dict):
        raise ValidationError("Public profile revision data must be an object.")
    organization_data = proposed_data.get("organization") or {}
    if not isinstance(organization_data, dict):
        raise ValidationError({"organization": "Public organization data must be an object."})
    cleaned = {"organization": _clean_public_organization(organization_data)}
    if organization.kind == Organization.Kind.DESIGNER:
        profile_data = proposed_data.get("profile") or {}
        if not isinstance(profile_data, dict):
            raise ValidationError({"profile": "Public Designer profile data must be an object."})
        cleaned["profile"] = _clean_designer_profile(profile_data)
    elif organization.kind != Organization.Kind.MANUFACTURER:
        raise ValidationError("Public profile revisions require a professional organization.")
    return cleaned


def current_public_profile_data(organization):
    organization_data = {
        "display_name": organization.display_name,
        "website": organization.website,
        "city": organization.city,
        "region": organization.region,
        "country": organization.country,
    }
    payload = {"organization": organization_data}
    if organization.kind == Organization.Kind.DESIGNER:
        profile = organization.designer_profile
        payload["profile"] = {
            "studio_name": profile.studio_name,
            "portfolio_url": profile.portfolio_url,
            "social_links": deepcopy(profile.social_links or {}),
        }
    return normalize_public_profile_data(
        organization=organization,
        proposed_data=payload,
    )


def _require_professional_profile_manager(actor, organization):
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise ValidationError("Only an approved active professional organization may propose public profile changes.")
    require_org_access(
        actor,
        organization,
        roles=[Membership.Role.OWNER, Membership.Role.MANAGER],
    )


@transaction.atomic
def save_public_profile_revision(
    *, organization, actor, proposed_data, request=None
):
    _require_professional_profile_manager(actor, organization)
    cleaned = normalize_public_profile_data(
        organization=organization,
        proposed_data=proposed_data,
    )
    submitted = organization.public_profile_revisions.filter(
        status=PublicProfileRevision.Status.SUBMITTED
    ).first()
    if submitted:
        if submitted.proposed_data == cleaned:
            return submitted
        raise ValidationError(
            "A public profile revision is already submitted and awaiting FABINZI review."
        )

    draft = organization.public_profile_revisions.filter(
        status=PublicProfileRevision.Status.DRAFT
    ).first()
    if draft is None:
        draft = PublicProfileRevision(
            organization=organization,
            created_by=actor,
        )
    draft.proposed_data = cleaned
    draft.full_clean()
    draft.save()
    record_audit_event(
        actor=actor,
        action="public_profile.revision.draft_saved",
        instance=draft,
        metadata={"organization_id": organization.pk},
        request=request,
    )
    return draft


@transaction.atomic
def submit_public_profile_revision(*, revision, actor, request=None):
    _require_professional_profile_manager(actor, revision.organization)
    if revision.status == PublicProfileRevision.Status.SUBMITTED:
        return revision
    if revision.status != PublicProfileRevision.Status.DRAFT:
        raise ValidationError("Only a draft public profile revision can be submitted.")
    normalized = normalize_public_profile_data(
        organization=revision.organization,
        proposed_data=revision.proposed_data,
    )
    if normalized == current_public_profile_data(revision.organization):
        raise ValidationError("There are no public profile changes to submit.")
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
        metadata={"organization_id": revision.organization_id},
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
            status=PublicProfileRevision.Status.SUBMITTED
        ).first()
    revision = save_public_profile_revision(
        organization=organization,
        actor=actor,
        proposed_data=cleaned,
        request=request,
    )
    if revision.status == PublicProfileRevision.Status.DRAFT:
        revision = submit_public_profile_revision(
            revision=revision,
            actor=actor,
            request=request,
        )
    return revision


def _apply_approved_public_data(revision):
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


@transaction.atomic
def review_public_profile_revision(
    *, revision, reviewer, decision, notes="", request=None
):
    if not reviewer.is_staff:
        raise PermissionDenied("Staff access required.")
    if decision not in {
        PublicProfileRevision.Status.APPROVED,
        PublicProfileRevision.Status.REJECTED,
    }:
        raise ValidationError("Unsupported public profile review decision.")
    if revision.status != PublicProfileRevision.Status.SUBMITTED:
        raise ValidationError("Only submitted public profile revisions can be reviewed.")
    if (
        decision == PublicProfileRevision.Status.APPROVED
        and revision.organization.verification_status
        != Organization.VerificationStatus.ACTIVE
    ):
        raise ValidationError(
            "A suspended or inactive professional organization cannot publish a profile revision."
        )

    if decision == PublicProfileRevision.Status.APPROVED:
        _apply_approved_public_data(revision)

    revision.status = decision
    revision.review_notes = str(notes or "").strip()
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
            "notes_present": bool(revision.review_notes),
        },
        request=request,
    )
    return revision
