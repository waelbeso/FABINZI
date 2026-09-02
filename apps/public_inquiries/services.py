import hashlib
import io
import secrets
import uuid
from datetime import date, timedelta
from pathlib import Path

import requests
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.mail import EmailMessage
from django.core.validators import EmailValidator
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from apps.artwork.models import DesignedProduct
from apps.artwork.public import public_artwork_queryset
from apps.audit.services import record_audit_event
from apps.design.models import GarmentDesign
from apps.integrations.models import IntegrationConfig
from apps.media.models import MediaAsset
from apps.media.services import _s3_client, active_provider, private_media_storage_mode
from apps.notifications.models import Notification
from apps.organizations.models import Membership, Organization
from apps.storefront.models import StoreProduct, Storefront
from apps.public_profiles.models import ManufacturerPublicProductApproval
from apps.public_profiles.services import approved_manufacturer_products, is_public_professional, manufacturer_product_approval_is_public
from .models import PublicInquiry, PublicInquiryAttachment, PublicInquiryEmailChallenge, PublicInquiryMessage


OTP_TTL_MINUTES = 10
ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024
MANAGE_ROLES = {Membership.Role.OWNER, Membership.Role.MANAGER}


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "")) or "unknown"


def _session_key(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key or ""


def _session_hash(request):
    return hashlib.sha256(_session_key(request).encode("utf-8")).hexdigest()


def _rate_limit(key, *, limit, window):
    cache_key = f"v2-5-public-inquiry:{key}"
    if cache.add(cache_key, 1, timeout=window):
        return
    try:
        value = cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, timeout=window)
        value = 1
    if value > limit:
        raise ValidationError("Too many requests. Please wait before trying again.")


def _deliver_otp(email, otp):
    subject = "FABINZI public inquiry verification code"
    body = f"Your FABINZI verification code is {otp}. It expires in {OTP_TTL_MINUTES} minutes."
    environment = str(getattr(settings, "ENVIRONMENT", "development")).lower()
    if environment in {"test", "testing"}:
        connection = mail.get_connection("django.core.mail.backends.locmem.EmailBackend")
        EmailMessage(subject, body, "no-reply@fabinzi.test", [email], connection=connection).send(fail_silently=False)
        return "test_email_backend"
    if settings.DEBUG or environment in {"development", "dev"}:
        connection = mail.get_connection("django.core.mail.backends.console.EmailBackend")
        EmailMessage(subject, body, "no-reply@localhost", [email], connection=connection).send(fail_silently=False)
        return "development_console_backend"
    cfg = IntegrationConfig.objects.filter(
        provider=IntegrationConfig.Provider.MAILGUN,
        enabled=True,
        last_test_status=IntegrationConfig.TestStatus.SUCCESS,
    ).first()
    if not cfg:
        raise ValidationError("Email verification is temporarily unavailable.")
    secret_map = cfg.get_secrets()
    domain = str((cfg.config or {}).get("domain") or "").strip()
    api_key = secret_map.get("api_key", "")
    if not domain or not api_key:
        raise ValidationError("Email verification is temporarily unavailable.")
    base = str((cfg.config or {}).get("api_base") or "https://api.mailgun.net").rstrip("/")
    sender = str((cfg.config or {}).get("from_email") or f"FABINZI <no-reply@{domain}>")
    response = requests.post(
        f"{base}/v3/{domain}/messages",
        auth=("api", api_key),
        data={"from": sender, "to": email, "subject": subject, "text": body},
        timeout=10,
    )
    response.raise_for_status()
    return "mailgun"


@transaction.atomic
def request_email_challenge(*, request, email):
    email = str(email or "").strip().lower()
    EmailValidator()(email)
    _rate_limit(f"otp-ip:{_client_ip(request)}", limit=5, window=600)
    _rate_limit(f"otp-email:{hashlib.sha256(email.encode()).hexdigest()}", limit=3, window=600)
    otp = f"{secrets.randbelow(1_000_000):06d}"
    challenge = PublicInquiryEmailChallenge.objects.create(
        email=email,
        session_key_hash=_session_hash(request),
        otp_hash=make_password(otp),
        expires_at=timezone.now() + timedelta(minutes=OTP_TTL_MINUTES),
    )
    try:
        backend = _deliver_otp(email, otp)
    except Exception as exc:
        challenge.delete()
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError("Email verification is temporarily unavailable.") from exc
    record_audit_event(
        actor=getattr(request, "user", None),
        action="public_inquiry.email_otp.requested",
        instance=challenge,
        metadata={"delivery_backend": backend},
        request=request,
    )
    return challenge


@transaction.atomic
def verify_email_challenge(*, request, reference, email, otp):
    _rate_limit(f"otp-verify:{_session_hash(request)}", limit=12, window=600)
    challenge = PublicInquiryEmailChallenge.objects.filter(reference=reference).first()
    if not challenge or challenge.email != str(email or "").strip().lower():
        raise ValidationError("Verification challenge is invalid.")
    if challenge.session_key_hash != _session_hash(request):
        raise ValidationError("Verification challenge belongs to another browser session.")
    if challenge.consumed_at:
        raise ValidationError("Verification challenge has already been used.")
    if challenge.expires_at <= timezone.now():
        raise ValidationError("Verification code has expired.")
    if challenge.attempt_count >= 5:
        raise ValidationError("Verification challenge is locked after too many attempts.")
    challenge.attempt_count += 1
    if not check_password(str(otp or "").strip(), challenge.otp_hash):
        challenge.save(update_fields=["attempt_count"])
        raise ValidationError("Verification code is incorrect.")
    challenge.verified_at = timezone.now()
    challenge.save(update_fields=["attempt_count", "verified_at"])
    request.session["public_inquiry_verified_email"] = {
        "email": challenge.email,
        "reference": str(challenge.reference),
    }
    record_audit_event(
        actor=getattr(request, "user", None),
        action="public_inquiry.email_otp.verified",
        instance=challenge,
        request=request,
    )
    return challenge


def _verified_challenge(request, email):
    marker = request.session.get("public_inquiry_verified_email") or {}
    if marker.get("email") != str(email or "").strip().lower():
        return None
    return PublicInquiryEmailChallenge.objects.filter(
        reference=marker.get("reference"),
        email=marker.get("email"),
        session_key_hash=_session_hash(request),
        verified_at__isnull=False,
        consumed_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).first()


def anonymous_email_verified(request, email):
    return bool(_verified_challenge(request, email))


def _published_store_product_qs():
    return StoreProduct.objects.filter(
        status=StoreProduct.Status.PUBLISHED,
        storefront__status=Storefront.Status.PUBLISHED,
        storefront__organization__verification_status=Organization.VerificationStatus.ACTIVE,
        designed_product__status=DesignedProduct.Status.PUBLISHED,
    )


def designer_public_references(organization):
    products = list(
        _published_store_product_qs()
        .filter(storefront__organization=organization)
        .select_related("designed_product__garment_version__design", "designed_product__artwork_version__artwork")[:100]
    )
    garments = {}
    ready = {}
    for product in products:
        ready[product.designed_product_id] = product.designed_product
        design = product.designed_product.garment_version.design
        garments[design.pk] = design
    artworks = list(public_artwork_queryset().filter(organization=organization).order_by("title")[:100])
    return {
        PublicInquiry.DesignerWorkKind.GARMENT_DESIGN: list(garments.values()),
        PublicInquiry.DesignerWorkKind.ARTWORK: artworks,
        PublicInquiry.DesignerWorkKind.READY_PRODUCT: list(ready.values()),
    }


def _resolve_designer_reference(organization, work_kind, work_id):
    try:
        work_id = int(work_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Select an approved public Designer work.") from exc
    if work_kind == PublicInquiry.DesignerWorkKind.GARMENT_DESIGN:
        obj = GarmentDesign.objects.filter(pk=work_id, organization=organization, status=GarmentDesign.Status.APPROVED).first()
        if not obj or not _published_store_product_qs().filter(storefront__organization=organization, designed_product__garment_version__design=obj).exists():
            raise ValidationError("Selected Garment Design is not currently public.")
        return {"garment_design": obj, "designer_work_kind": work_kind}
    if work_kind == PublicInquiry.DesignerWorkKind.ARTWORK:
        obj = public_artwork_queryset().filter(pk=work_id, organization=organization).first()
        if not obj:
            raise ValidationError("Selected Artwork is not currently public.")
        return {"artwork": obj, "designer_work_kind": work_kind}
    if work_kind == PublicInquiry.DesignerWorkKind.READY_PRODUCT:
        obj = DesignedProduct.objects.filter(pk=work_id, organization=organization, status=DesignedProduct.Status.PUBLISHED).first()
        if not obj or not _published_store_product_qs().filter(storefront__organization=organization, designed_product=obj).exists():
            raise ValidationError("Selected Ready Designed Product is not currently public.")
        return {"ready_product": obj, "designer_work_kind": work_kind}
    raise ValidationError("Select an approved public Designer work type.")


def _resolve_manufacturer_approval(organization, approval_id):
    approval = ManufacturerPublicProductApproval.objects.filter(
        pk=approval_id,
        manufacturer=organization,
    ).select_related(
        "manufacturer__public_state",
        "manufacturer__onboarding_application",
        "store_product__storefront",
        "store_product__designed_product",
    ).first()
    if not approval or not manufacturer_product_approval_is_public(approval):
        raise ValidationError("Selected product is not currently approved and public for this Manufacturer.")
    return approval


def _positive_quantity(value):
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Enter a valid quantity.") from exc
    if value < 1 or value > 1_000_000:
        raise ValidationError("Quantity must be between 1 and 1,000,000.")
    return value


def _desired_date(value):
    if not value:
        return None
    try:
        result = date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValidationError("Enter a valid desired date.") from exc
    if result < timezone.localdate():
        raise ValidationError("Desired date cannot be in the past.")
    return result


def _private_attachment_asset(upload, *, actor=None):
    if not upload:
        return None
    size = getattr(upload, "size", 0) or 0
    if size <= 0 or size > ATTACHMENT_MAX_BYTES:
        raise ValidationError("Inquiry attachment must be between 1 byte and 10 MB.")
    payload = upload.read()
    filename = Path(getattr(upload, "name", "attachment")).name[:255]
    suffix = Path(filename).suffix.lower()
    if payload.startswith(b"%PDF-") and suffix == ".pdf":
        mime_type, extension = "application/pdf", ".pdf"
    else:
        try:
            with Image.open(io.BytesIO(payload)) as image:
                image.verify()
            with Image.open(io.BytesIO(payload)) as image:
                fmt = (image.format or "").upper()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ValidationError("Inquiry attachments accept PDF, PNG, JPEG or WebP files only.") from exc
        mapping = {"PNG": ("image/png", ".png"), "JPEG": ("image/jpeg", ".jpg"), "WEBP": ("image/webp", ".webp")}
        if fmt not in mapping:
            raise ValidationError("Inquiry attachments accept PDF, PNG, JPEG or WebP files only.")
        mime_type, extension = mapping[fmt]
    key = f"inquiry-private/{uuid.uuid4().hex}{extension}"
    if private_media_storage_mode() == "local":
        stored_key = default_storage.save(key, ContentFile(payload))
        provider = MediaAsset.Provider.LOCAL_DEV
    else:
        integration = active_provider(IntegrationConfig.Provider.AMAZON_S3)
        bucket = (integration.config or {}).get("bucket", "")
        if not bucket:
            raise ValidationError("Private inquiry storage is temporarily unavailable.")
        _s3_client(integration).put_object(
            Bucket=bucket,
            Key=key,
            Body=payload,
            ContentType=mime_type,
            CacheControl="private, no-store",
        )
        stored_key = key
        provider = MediaAsset.Provider.AMAZON_S3
    return MediaAsset.objects.create(
        provider=provider,
        provider_asset_id=stored_key,
        original_filename=filename,
        mime_type=mime_type,
        size_bytes=len(payload),
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        access=MediaAsset.Access.PRIVATE,
        metadata={"public_inquiry_attachment": True},
        uploaded_by=actor if getattr(actor, "is_authenticated", False) else None,
    )


def _notify_target(inquiry):
    destination = (
        reverse("designer-public-inquiry-detail", args=[inquiry.pk])
        if inquiry.target_kind == PublicInquiry.TargetKind.DESIGNER
        else reverse("manufacturer-public-inquiry-detail", args=[inquiry.pk])
    ) + f"?org={inquiry.target_organization_id}"
    for membership in inquiry.target_organization.memberships.filter(
        is_active=True,
        role__in=MANAGE_ROLES,
    ).select_related("user"):
        Notification.objects.create(
            recipient=membership.user,
            type="public_inquiry.received",
            title_en="New public inquiry",
            title_ar="استفسار عام جديد",
            body_en="A verified public inquiry was routed to your FABINZI professional profile.",
            body_ar="تم توجيه استفسار عام موثق إلى ملفك المهني على FABINZI.",
            destination=destination,
        )


@transaction.atomic
def submit_public_inquiry(*, request, target_organization, data, attachment=None):
    if target_organization.kind not in {Organization.Kind.DESIGNER, Organization.Kind.MANUFACTURER}:
        raise ValidationError("Public inquiry target must be a professional organization.")
    target_kind = PublicInquiry.TargetKind.DESIGNER if target_organization.kind == Organization.Kind.DESIGNER else PublicInquiry.TargetKind.MANUFACTURER
    if not is_public_professional(target_organization, kind=target_organization.kind):
        raise ValidationError("This professional profile is not currently accepting public inquiries.")
    _rate_limit(f"submit-ip:{_client_ip(request)}", limit=8, window=3600)
    _rate_limit(f"submit-session:{_session_hash(request)}", limit=5, window=3600)
    user = request.user if getattr(request.user, "is_authenticated", False) else None
    email = str(data.get("email") or (user.email if user else "")).strip().lower()
    challenge = None
    if not user:
        if not email:
            raise ValidationError("Verify your email before final submission.")
        challenge = _verified_challenge(request, email)
        if not challenge:
            raise ValidationError("Verify your email before final submission.")

    kwargs = {}
    if target_kind == PublicInquiry.TargetKind.DESIGNER:
        kwargs.update(_resolve_designer_reference(target_organization, data.get("work_kind"), data.get("work_id")))
    else:
        kwargs["manufacturer_product_approval"] = _resolve_manufacturer_approval(target_organization, data.get("product_approval_id"))

    inquiry = PublicInquiry(
        target_kind=target_kind,
        target_organization=target_organization,
        sender_user=user,
        sender_email=email,
        sender_email_verified=bool(user or challenge),
        status=PublicInquiry.Status.SUBMITTED,
        quantity=_positive_quantity(data.get("quantity")),
        size_requirements={"text": str(data.get("sizes") or "").strip()[:1000]},
        color_requirements=[item.strip()[:120] for item in str(data.get("colors") or "").replace("\n", ",").split(",") if item.strip()][:40],
        customization_description=str(data.get("customization_description") or "").strip()[:5000],
        delivery_city=str(data.get("delivery_city") or "").strip()[:120],
        delivery_country=str(data.get("delivery_country") or "").strip().upper()[:2],
        desired_date=_desired_date(data.get("desired_date")),
        requirements=str(data.get("requirements") or "").strip()[:10000],
        notes=str(data.get("notes") or "").strip()[:5000],
        submitted_at=timezone.now(),
        **kwargs,
    )
    inquiry.full_clean()
    inquiry.save()
    if attachment:
        asset = _private_attachment_asset(attachment, actor=user)
        attached = PublicInquiryAttachment(inquiry=inquiry, media_asset=asset, uploaded_by=user)
        attached.full_clean()
        attached.save()
    if challenge:
        challenge.consumed_at = timezone.now()
        challenge.save(update_fields=["consumed_at"])
        request.session.pop("public_inquiry_verified_email", None)
    record_audit_event(
        actor=user,
        action="public_inquiry.submitted",
        instance=inquiry,
        metadata={"target_organization_id": target_organization.pk, "target_kind": target_kind},
        request=request,
    )
    _notify_target(inquiry)
    refs = list(request.session.get("public_inquiry_refs") or [])
    if str(inquiry.reference) not in refs:
        refs.append(str(inquiry.reference))
    request.session["public_inquiry_refs"] = refs[-20:]
    return inquiry


def can_view_inquiry(request, inquiry, *, professional=False):
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        if user.is_staff:
            return True
        if inquiry.sender_user_id == user.pk and not professional:
            return True
        if inquiry.target_organization.memberships.filter(user=user, is_active=True, role__in=MANAGE_ROLES).exists():
            return True
    return str(inquiry.reference) in set(request.session.get("public_inquiry_refs") or []) and not professional


def _require_professional(actor, inquiry):
    if not getattr(actor, "is_authenticated", False):
        raise PermissionDenied("Sign in required.")
    if actor.is_staff:
        return
    if not inquiry.target_organization.memberships.filter(user=actor, is_active=True, role__in=MANAGE_ROLES).exists():
        raise PermissionDenied("Only an Owner or Manager may handle public inquiries.")


@transaction.atomic
def add_inquiry_message(*, inquiry, actor=None, body, request=None, professional=False):
    body = str(body or "").strip()
    if not body:
        raise ValidationError("Message cannot be empty.")
    if inquiry.status in {PublicInquiry.Status.CLOSED, PublicInquiry.Status.SPAM}:
        raise ValidationError("This inquiry is closed.")
    if professional:
        _require_professional(actor, inquiry)
        role = PublicInquiryMessage.SenderRole.STAFF if actor.is_staff else PublicInquiryMessage.SenderRole.PROFESSIONAL
    else:
        if not can_view_inquiry(request, inquiry):
            raise PermissionDenied("Inquiry access denied.")
        role = PublicInquiryMessage.SenderRole.VISITOR
    message = PublicInquiryMessage.objects.create(
        inquiry=inquiry,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        sender_role=role,
        body=body[:10000],
    )
    if professional:
        inquiry.status = PublicInquiry.Status.RESPONDED
        inquiry.save(update_fields=["status", "updated_at"])
        if inquiry.sender_user_id:
            Notification.objects.create(
                recipient=inquiry.sender_user,
                type="public_inquiry.response",
                title_en="Your FABINZI inquiry has a response",
                title_ar="يوجد رد على استفسارك في FABINZI",
                body_en="Open FABINZI to read the response. Direct professional contact details remain private.",
                body_ar="افتح FABINZI لقراءة الرد. تظل بيانات الاتصال المباشر للشريك المهني خاصة.",
                destination=reverse("public-inquiry-status", args=[inquiry.reference]),
            )
    record_audit_event(
        actor=actor,
        action="public_inquiry.message.added",
        instance=inquiry,
        metadata={"sender_role": role},
        request=request,
    )
    return message


@transaction.atomic
def transition_public_inquiry(*, inquiry, actor, target_status, request=None, staff_notes=""):
    allowed = {
        PublicInquiry.Status.SUBMITTED: {PublicInquiry.Status.HANDLING, PublicInquiry.Status.CLOSED, PublicInquiry.Status.SPAM},
        PublicInquiry.Status.HANDLING: {PublicInquiry.Status.RESPONDED, PublicInquiry.Status.CLOSED, PublicInquiry.Status.SPAM},
        PublicInquiry.Status.RESPONDED: {PublicInquiry.Status.HANDLING, PublicInquiry.Status.CLOSED, PublicInquiry.Status.SPAM},
    }
    _require_professional(actor, inquiry)
    if target_status not in allowed.get(inquiry.status, set()):
        raise ValidationError("Unsupported public inquiry transition.")
    previous = inquiry.status
    inquiry.status = target_status
    if actor.is_staff:
        inquiry.handled_by = actor
        if staff_notes:
            inquiry.staff_notes = str(staff_notes)[:5000]
    inquiry.closed_at = timezone.now() if target_status in {PublicInquiry.Status.CLOSED, PublicInquiry.Status.SPAM} else None
    inquiry.save(update_fields=["status", "handled_by", "staff_notes", "closed_at", "updated_at"])
    action = "public_inquiry.spam" if target_status == PublicInquiry.Status.SPAM else ("public_inquiry.closed" if target_status == PublicInquiry.Status.CLOSED else "public_inquiry.handling")
    record_audit_event(
        actor=actor,
        action=action,
        instance=inquiry,
        metadata={"previous_status": previous, "new_status": target_status},
        request=request,
    )
    return inquiry
