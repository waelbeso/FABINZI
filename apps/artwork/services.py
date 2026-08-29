from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import record_audit_event
from apps.design.models import GarmentDesignVersion
from apps.media.designer_services import claim_or_require_private_designer_asset, require_private_designer_asset
from apps.media.models import MediaAsset
from apps.notifications.models import Notification
from apps.organizations.models import Membership, Organization
from apps.organizations.services import require_org_access, user_has_org_access
from .models import Artwork, ArtworkAsset, ArtworkPlacement, ArtworkReview, ArtworkVersion, DesignedProduct, IPCase, IPCaseEvidence, IPDeclaration

ARTWORK_EDIT_ROLES = [Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.DESIGNER, Membership.Role.DESIGN_MANAGER]
ARTWORK_MANAGE_ROLES = [Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.DESIGN_MANAGER]


def require_active_designer_org(organization):
    if organization.kind != Organization.Kind.DESIGNER or organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise ValidationError("An approved active Designer business is required.")


def user_can_view_artwork(user, artwork):
    if artwork.status == Artwork.Status.APPROVED:
        return True
    return bool(user and user.is_authenticated and (user.is_staff or user_has_org_access(user, artwork.organization)))


def require_artwork_access(user, artwork, *, edit=False):
    if user.is_staff and not edit:
        return True
    return require_org_access(user, artwork.organization, roles=ARTWORK_EDIT_ROLES if edit else None)


def _public_preview_rows(artwork):
    return ArtworkAsset.objects.filter(version__artwork=artwork, kind=ArtworkAsset.Kind.PREVIEW, media_asset__metadata__artwork_public_derivative=True).select_related("media_asset", "version")


def _set_public_derivative_state(media, *, enabled, version=None):
    metadata = dict(media.metadata or {})
    if enabled:
        media.access = MediaAsset.Access.PUBLIC
        metadata["artwork_public_derivative"] = True
        metadata["artwork_version_id"] = version.pk if version else metadata.get("artwork_version_id")
        metadata["public_url"] = f"/artwork/media/{media.pk}/"
        metadata.pop("artwork_public_revoked", None)
    else:
        media.access = MediaAsset.Access.PRIVATE
        metadata.pop("public_url", None)
        metadata["artwork_public_revoked"] = True
    media.metadata = metadata
    media.save(update_fields=["access", "metadata"])
    return media


def revoke_public_preview_derivatives(*, artwork, actor=None, reason="state_change", request=None):
    for row in _public_preview_rows(artwork):
        if row.media_asset.access != MediaAsset.Access.PRIVATE or (row.media_asset.metadata or {}).get("public_url"):
            _set_public_derivative_state(row.media_asset, enabled=False)
            record_audit_event(actor=actor, action="artwork.preview.revoked", instance=row.version, metadata={"artwork_id": artwork.pk, "media_asset_id": row.media_asset_id, "reason": reason}, request=request)


def ensure_public_preview_for_version(*, version, actor=None, request=None):
    if version.status != ArtworkVersion.Status.APPROVED or version.artwork.status != Artwork.Status.APPROVED:
        raise ValidationError("Only an approved Artwork Version can publish a public preview.")
    existing_public = version.assets.filter(kind=ArtworkAsset.Kind.PREVIEW, media_asset__access=MediaAsset.Access.PUBLIC, media_asset__mime_type__startswith="image/").select_related("media_asset").order_by("id").first()
    if existing_public and not (existing_public.media_asset.metadata or {}).get("artwork_public_revoked"):
        return existing_public
    source_row = version.assets.filter(kind=ArtworkAsset.Kind.PREVIEW, media_asset__access=MediaAsset.Access.PRIVATE, media_asset__mime_type__startswith="image/", media_asset__metadata__designer_private_upload=True, media_asset__metadata__organization_id=version.artwork.organization_id).select_related("media_asset").order_by("id").first()
    if not source_row:
        raise ValidationError("Approved Artwork requires a valid private Designer preview before it can be published.")
    source = source_row.media_asset
    derivative_row = version.assets.filter(kind=ArtworkAsset.Kind.PREVIEW, media_asset__metadata__artwork_public_derivative=True, media_asset__metadata__source_media_asset_id=source.pk).select_related("media_asset").order_by("id").first()
    if derivative_row:
        _set_public_derivative_state(derivative_row.media_asset, enabled=True, version=version)
        return derivative_row
    derivative = MediaAsset.objects.create(provider=source.provider, provider_asset_id=source.provider_asset_id, original_filename=source.original_filename, mime_type=source.mime_type, size_bytes=source.size_bytes, checksum_sha256=source.checksum_sha256, access=MediaAsset.Access.PUBLIC, metadata={"artwork_public_derivative": True, "source_media_asset_id": source.pk, "organization_id": version.artwork.organization_id, "artwork_version_id": version.pk, "width": (source.metadata or {}).get("width"), "height": (source.metadata or {}).get("height")}, uploaded_by=source.uploaded_by)
    _set_public_derivative_state(derivative, enabled=True, version=version)
    derivative_row = ArtworkAsset.objects.create(version=version, kind=ArtworkAsset.Kind.PREVIEW, media_asset=derivative, label="Approved public preview")
    record_audit_event(actor=actor, action="artwork.preview.published", instance=version, metadata={"artwork_id": version.artwork_id, "source_media_asset_id": source.pk, "public_media_asset_id": derivative.pk}, request=request)
    return derivative_row


@transaction.atomic
def create_artwork(*, organization, actor, title, description="", tags=None, request=None):
    require_active_designer_org(organization)
    require_org_access(actor, organization, roles=ARTWORK_EDIT_ROLES)
    artwork = Artwork(organization=organization, title=title, description=description, tags=tags or [], created_by=actor)
    artwork.full_clean(); artwork.save()
    version = ArtworkVersion.objects.create(artwork=artwork, version_number=1, created_by=actor)
    record_audit_event(actor=actor, action="artwork.created", instance=artwork, metadata={"organization_id": organization.pk, "version_id": version.pk}, request=request)
    return artwork


@transaction.atomic
def create_artwork_revision(*, artwork, actor, request=None):
    require_artwork_access(actor, artwork, edit=True)
    latest = artwork.versions.order_by("-version_number").first()
    if latest and latest.status not in {ArtworkVersion.Status.REVISION_REQUIRED, ArtworkVersion.Status.APPROVED, ArtworkVersion.Status.REJECTED}:
        raise ValidationError("A new artwork revision can only follow a reviewed version.")
    revoke_public_preview_derivatives(artwork=artwork, actor=actor, reason="new_revision", request=request)
    number = (artwork.versions.aggregate(m=Max("version_number"))["m"] or 0) + 1
    version = ArtworkVersion.objects.create(artwork=artwork, version_number=number, created_by=actor, color_profile=latest.color_profile if latest else "", production_notes=latest.production_notes if latest else "", metadata=latest.metadata if latest else {})
    artwork.status = Artwork.Status.DRAFT; artwork.save(update_fields=["status", "updated_at"])
    record_audit_event(actor=actor, action="artwork.revision.created", instance=version, metadata={"artwork_id": artwork.pk}, request=request)
    return version


def require_artwork_draft(version, actor):
    require_artwork_access(actor, version.artwork, edit=True)
    if version.status != ArtworkVersion.Status.DRAFT:
        raise ValidationError("Submitted/reviewed Artwork Versions are immutable; create a new revision instead.")


@transaction.atomic
def add_artwork_asset(*, version, actor, media_asset, kind, label="", request=None):
    require_artwork_draft(version, actor)
    organization = version.artwork.organization
    if kind in {ArtworkAsset.Kind.SOURCE, ArtworkAsset.Kind.RIGHTS_EVIDENCE}:
        claim_or_require_private_designer_asset(asset=media_asset, organization=organization, actor=actor, purpose=f"artwork_{kind}")
    elif kind == ArtworkAsset.Kind.PREVIEW and media_asset.access == MediaAsset.Access.PRIVATE:
        claim_or_require_private_designer_asset(asset=media_asset, organization=organization, actor=actor, purpose="artwork_preview")
    elif media_asset.uploaded_by_id and media_asset.uploaded_by_id != actor.pk and not actor.is_staff:
        raise PermissionDenied("This media asset is not owned by the current user.")
    asset = ArtworkAsset(version=version, kind=kind, media_asset=media_asset, label=label)
    asset.full_clean(); asset.save()
    record_audit_event(actor=actor, action="artwork.asset.added", instance=asset, metadata={"artwork_id": version.artwork_id, "kind": kind}, request=request)
    return asset


@transaction.atomic
def set_ip_declaration(*, version, actor, rights_basis, rights_holder_name, third_party_content=False, details="", accepts_ip_policy=False, request=None):
    require_artwork_draft(version, actor)
    declaration, _ = IPDeclaration.objects.update_or_create(version=version, defaults={"rights_basis": rights_basis, "rights_holder_name": rights_holder_name, "third_party_content": third_party_content, "details": details, "accepts_ip_policy": accepts_ip_policy, "declared_by": actor})
    record_audit_event(actor=actor, action="artwork.ip.declared", instance=declaration, metadata={"artwork_id": version.artwork_id, "rights_basis": rights_basis}, request=request)
    return declaration


def validate_artwork_ready(version):
    try:
        declaration = IPDeclaration.objects.get(version=version)
    except IPDeclaration.DoesNotExist:
        raise ValidationError("IP rights declaration is required.")
    if not declaration.accepts_ip_policy:
        raise ValidationError("IP policy acceptance is required.")
    if not declaration.rights_holder_name:
        raise ValidationError("Rights holder name is required.")
    if declaration.third_party_content and not version.assets.filter(kind=ArtworkAsset.Kind.RIGHTS_EVIDENCE).exists():
        raise ValidationError("Rights evidence is required when third-party content is declared.")
    if not version.assets.filter(kind=ArtworkAsset.Kind.PREVIEW).exists():
        raise ValidationError("Artwork preview is required.")
    if not version.assets.filter(kind=ArtworkAsset.Kind.SOURCE).exists():
        raise ValidationError("Private production source is required.")


@transaction.atomic
def submit_artwork_version(*, version, actor, request=None):
    require_artwork_draft(version, actor)
    validate_artwork_ready(version)
    version.status = ArtworkVersion.Status.SUBMITTED; version.submitted_at = timezone.now(); version.save(update_fields=["status", "submitted_at"])
    version.artwork.status = Artwork.Status.IN_REVIEW; version.artwork.save(update_fields=["status", "updated_at"])
    record_audit_event(actor=actor, action="artwork.version.submitted", instance=version, metadata={"artwork_id": version.artwork_id}, request=request)
    return version


@transaction.atomic
def review_artwork_version(*, version, reviewer, decision, notes="", request=None):
    if not reviewer.is_staff:
        raise PermissionDenied("Staff access required.")
    if version.status != ArtworkVersion.Status.SUBMITTED:
        raise ValidationError("Only submitted Artwork Versions can be reviewed.")
    if decision not in dict(ArtworkReview.Decision.choices):
        raise ValidationError("Unsupported Artwork review decision.")
    ArtworkReview.objects.create(version=version, reviewer=reviewer, decision=decision, notes=notes)
    version.status = decision; version.reviewed_at = timezone.now(); version.reviewed_by = reviewer; version.review_notes = notes
    version.save(update_fields=["status", "reviewed_at", "reviewed_by", "review_notes"])
    status_map = {ArtworkReview.Decision.APPROVED: Artwork.Status.APPROVED, ArtworkReview.Decision.REVISION_REQUIRED: Artwork.Status.REVISION_REQUIRED, ArtworkReview.Decision.REJECTED: Artwork.Status.REJECTED}
    version.artwork.status = status_map[decision]; version.artwork.save(update_fields=["status", "updated_at"])
    if decision == ArtworkReview.Decision.APPROVED:
        ensure_public_preview_for_version(version=version, actor=reviewer, request=request)
    else:
        revoke_public_preview_derivatives(artwork=version.artwork, actor=reviewer, reason=decision, request=request)
    title_en = {"approved":"Artwork approved","revision_required":"Artwork needs revision","rejected":"Artwork rejected"}[decision]
    title_ar = {"approved":"تم اعتماد العمل الفني","revision_required":"العمل الفني يحتاج إلى تعديلات","rejected":"تم رفض العمل الفني"}[decision]
    for membership in version.artwork.organization.memberships.filter(is_active=True).select_related("user"):
        Notification.objects.create(recipient=membership.user, type="artwork_review", title_en=title_en, title_ar=title_ar, body_en=notes, body_ar=notes, destination=f"/designer/artworks/{version.artwork_id}/")
    record_audit_event(actor=reviewer, action=f"artwork.version.{decision}", instance=version, metadata={"artwork_id": version.artwork_id, "notes_present": bool(notes)}, request=request)
    return version


@transaction.atomic
def create_designed_product(*, organization, actor, garment_version, artwork_version, title, description="", request=None):
    require_active_designer_org(organization)
    require_org_access(actor, organization, roles=ARTWORK_EDIT_ROLES)
    if garment_version.status != GarmentDesignVersion.Status.APPROVED:
        raise ValidationError("Designed Products require an approved Garment Design Version.")
    if artwork_version.status != ArtworkVersion.Status.APPROVED:
        raise ValidationError("Designed Products require an approved Artwork Version.")
    product = DesignedProduct(organization=organization, garment_version=garment_version, artwork_version=artwork_version, title=title, description=description, created_by=actor)
    product.full_clean(); product.save()
    record_audit_event(actor=actor, action="designed_product.created", instance=product, metadata={"organization_id": organization.pk}, request=request)
    return product


@transaction.atomic
def add_product_placement(*, product, actor, decoration_zone, transform, production_method, request=None):
    require_org_access(actor, product.organization, roles=ARTWORK_EDIT_ROLES)
    if product.status != DesignedProduct.Status.DRAFT:
        raise ValidationError("Only draft Designed Products can be edited.")
    placement = ArtworkPlacement(product=product, decoration_zone=decoration_zone, transform=transform or {}, production_method=production_method)
    placement.full_clean(); placement.save()
    record_audit_event(actor=actor, action="designed_product.placement.added", instance=placement, metadata={"product_id": product.pk, "zone_id": decoration_zone.pk}, request=request)
    return placement


@transaction.atomic
def publish_designed_product(*, product, actor, request=None):
    require_org_access(actor, product.organization, roles=ARTWORK_MANAGE_ROLES)
    if product.status != DesignedProduct.Status.DRAFT:
        raise ValidationError("Only draft Designed Products can be published.")
    if product.garment_version.status != GarmentDesignVersion.Status.APPROVED or product.artwork_version.status != ArtworkVersion.Status.APPROVED:
        raise ValidationError("Garment Design and Artwork approvals are required.")
    if not product.placements.exists():
        raise ValidationError("At least one Artwork placement is required.")
    product.status = DesignedProduct.Status.PUBLISHED; product.save(update_fields=["status", "updated_at"])
    record_audit_event(actor=actor, action="designed_product.published", instance=product, request=request)
    return product


@transaction.atomic
def create_ip_case(*, actor=None, artwork=None, designed_product=None, reporter_name, reporter_email, claimant_rights, allegation, request=None):
    case = IPCase(artwork=artwork, designed_product=designed_product, reporter_name=reporter_name, reporter_email=reporter_email, claimant_rights=claimant_rights, allegation=allegation, created_by=actor if getattr(actor, "is_authenticated", False) else None)
    case.full_clean(); case.save()
    record_audit_event(actor=actor if getattr(actor, "is_authenticated", False) else None, action="ip_case.created", instance=case, metadata={"artwork_id": case.artwork_id, "designed_product_id": case.designed_product_id}, request=request)
    return case


@transaction.atomic
def add_ip_case_evidence(*, case, actor, media_asset, description="", request=None):
    if media_asset.access != MediaAsset.Access.PRIVATE:
        raise ValidationError("IP case evidence must remain private.")
    if (media_asset.metadata or {}).get("studio_private_upload"):
        raise ValidationError("Customer Studio uploads cannot be attached as Designer IP evidence.")
    target_org = case.artwork.organization if case.artwork_id else case.designed_product.organization
    if (media_asset.metadata or {}).get("designer_private_upload"):
        require_private_designer_asset(asset=media_asset, organization=target_org, actor=actor)
    elif media_asset.uploaded_by_id and actor and media_asset.uploaded_by_id != actor.pk and not actor.is_staff:
        raise PermissionDenied("This media asset is not owned by the current user.")
    evidence = IPCaseEvidence(case=case, media_asset=media_asset, description=description, submitted_by=actor)
    evidence.full_clean(); evidence.save()
    record_audit_event(actor=actor, action="ip_case.evidence.added", instance=evidence, metadata={"case_id": case.pk}, request=request)
    return evidence


@transaction.atomic
def moderate_ip_case(*, case, reviewer, status, resolution=IPCase.Resolution.NONE, notes="", request=None):
    if not reviewer.is_staff:
        raise PermissionDenied("Staff access required.")
    if status not in dict(IPCase.Status.choices) or resolution not in dict(IPCase.Resolution.choices):
        raise ValidationError("Unsupported moderation state.")
    case.status = status; case.resolution = resolution; case.staff_notes = notes; case.assigned_to = reviewer
    if status in {IPCase.Status.RESOLVED, IPCase.Status.DISMISSED}:
        case.resolved_at = timezone.now()
    case.save()
    target_artwork = case.artwork or (case.designed_product.artwork_version.artwork if case.designed_product_id else None)
    if resolution == IPCase.Resolution.TAKEDOWN:
        if target_artwork:
            target_artwork.status = Artwork.Status.SUSPENDED; target_artwork.save(update_fields=["status", "updated_at"])
            revoke_public_preview_derivatives(artwork=target_artwork, actor=reviewer, reason="ip_takedown", request=request)
            DesignedProduct.objects.filter(artwork_version__artwork=target_artwork, status=DesignedProduct.Status.PUBLISHED).update(status=DesignedProduct.Status.SUSPENDED)
        if case.designed_product_id:
            case.designed_product.status = DesignedProduct.Status.SUSPENDED; case.designed_product.save(update_fields=["status", "updated_at"])
    elif resolution == IPCase.Resolution.RESTORED:
        if target_artwork and target_artwork.versions.filter(status=ArtworkVersion.Status.APPROVED).exists():
            target_artwork.status = Artwork.Status.APPROVED; target_artwork.save(update_fields=["status", "updated_at"])
            approved_version = target_artwork.versions.filter(status=ArtworkVersion.Status.APPROVED).order_by("-version_number").first()
            ensure_public_preview_for_version(version=approved_version, actor=reviewer, request=request)
        if case.designed_product_id and case.designed_product.garment_version.status == GarmentDesignVersion.Status.APPROVED and case.designed_product.artwork_version.status == ArtworkVersion.Status.APPROVED:
            case.designed_product.status = DesignedProduct.Status.PUBLISHED; case.designed_product.save(update_fields=["status", "updated_at"])
    record_audit_event(actor=reviewer, action="ip_case.moderated", instance=case, metadata={"status": status, "resolution": resolution}, request=request)
    return case
