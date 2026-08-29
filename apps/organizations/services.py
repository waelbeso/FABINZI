from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit_event
from apps.notifications.models import Notification
from .models import DesignerProfile, ManufacturerProfile, Membership, OnboardingApplication, Organization


def user_has_org_access(user, organization, *, roles=None):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    qs = Membership.objects.filter(user=user, organization=organization, is_active=True)
    if roles:
        qs = qs.filter(role__in=roles)
    return qs.exists()


def require_org_access(user, organization, *, roles=None):
    if not user_has_org_access(user, organization, roles=roles):
        raise PermissionDenied("You do not have access to this business.")
    return True


@transaction.atomic
def create_designer_onboarding(*, user, organization_data, profile_data, request=None):
    org = Organization.objects.create(kind=Organization.Kind.DESIGNER, created_by=user, **organization_data)
    Membership.objects.create(organization=org, user=user, role=Membership.Role.OWNER)
    DesignerProfile.objects.create(organization=org, **profile_data)
    application = OnboardingApplication.objects.create(organization=org)
    record_audit_event(actor=user, action="onboarding.designer.created", instance=application, metadata={"organization_id": org.pk}, request=request)
    return application


@transaction.atomic
def create_manufacturer_onboarding(*, user, organization_data, profile_data, request=None):
    org = Organization.objects.create(kind=Organization.Kind.MANUFACTURER, created_by=user, **organization_data)
    Membership.objects.create(organization=org, user=user, role=Membership.Role.OWNER)
    ManufacturerProfile.objects.create(organization=org, **profile_data)
    application = OnboardingApplication.objects.create(organization=org)
    record_audit_event(actor=user, action="onboarding.manufacturer.created", instance=application, metadata={"organization_id": org.pk}, request=request)
    return application


def _validate_submission(application):
    org = application.organization
    if not org.display_name or not org.email:
        raise ValidationError("Business name and email are required.")
    if org.kind == Organization.Kind.DESIGNER:
        profile = org.designer_profile
        if not profile.terms_accepted:
            raise ValidationError("Terms must be accepted before submission.")
    else:
        profile = org.manufacturer_profile
        if not profile.terms_accepted:
            raise ValidationError("Terms must be accepted before submission.")
        if not profile.commercial_registration:
            raise ValidationError("Commercial registration is required before submission.")


@transaction.atomic
def submit_application(*, application, actor, request=None):
    require_org_access(actor, application.organization, roles=[Membership.Role.OWNER, Membership.Role.MANAGER])
    if application.status not in {OnboardingApplication.Status.DRAFT, OnboardingApplication.Status.REVISION_REQUIRED}:
        raise ValidationError("This application cannot be submitted from its current state.")
    _validate_submission(application)
    application.status = OnboardingApplication.Status.SUBMITTED
    application.submitted_at = timezone.now()
    application.reviewed_at = None
    application.reviewed_by = None
    application.save(update_fields=["status", "submitted_at", "reviewed_at", "reviewed_by", "updated_at"])
    application.organization.verification_status = Organization.VerificationStatus.PENDING
    application.organization.save(update_fields=["verification_status", "updated_at"])
    record_audit_event(actor=actor, action="onboarding.submitted", instance=application, metadata={"organization_id": application.organization_id}, request=request)
    return application


@transaction.atomic
def review_application(*, application, reviewer, decision, notes="", request=None):
    if not reviewer.is_staff:
        raise PermissionDenied("Staff access required.")
    allowed = {OnboardingApplication.Status.APPROVED, OnboardingApplication.Status.REJECTED, OnboardingApplication.Status.REVISION_REQUIRED}
    if decision not in allowed:
        raise ValidationError("Unsupported review decision.")
    if application.status != OnboardingApplication.Status.SUBMITTED:
        raise ValidationError("Only submitted applications can be reviewed.")

    application.status = decision
    application.review_notes = notes
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    if decision == OnboardingApplication.Status.REVISION_REQUIRED:
        application.revision_count += 1
        org_status = Organization.VerificationStatus.DRAFT
    elif decision == OnboardingApplication.Status.APPROVED:
        org_status = Organization.VerificationStatus.ACTIVE
    else:
        org_status = Organization.VerificationStatus.REJECTED

    application.save(update_fields=["status", "review_notes", "reviewed_by", "reviewed_at", "revision_count", "updated_at"])
    application.organization.verification_status = org_status
    application.organization.save(update_fields=["verification_status", "updated_at"])

    title_en = {OnboardingApplication.Status.APPROVED: "Business application approved", OnboardingApplication.Status.REJECTED: "Business application rejected", OnboardingApplication.Status.REVISION_REQUIRED: "Business application needs revision"}[decision]
    title_ar = {OnboardingApplication.Status.APPROVED: "تمت الموافقة على طلب النشاط", OnboardingApplication.Status.REJECTED: "تم رفض طلب النشاط", OnboardingApplication.Status.REVISION_REQUIRED: "طلب النشاط يحتاج إلى تعديلات"}[decision]
    for membership in application.organization.memberships.filter(is_active=True).select_related("user"):
        Notification.objects.create(recipient=membership.user, type="business_onboarding_review", title_en=title_en, title_ar=title_ar, body_en=notes, body_ar=notes, destination="/designer/" if application.organization.kind == Organization.Kind.DESIGNER else "/manufacturer/")
    record_audit_event(actor=reviewer, action=f"onboarding.{decision}", instance=application, metadata={"organization_id": application.organization_id, "notes_present": bool(notes)}, request=request)
    return application


@transaction.atomic
def update_onboarding(*, application, actor, organization_data, profile_data, request=None):
    require_org_access(actor, application.organization, roles=[Membership.Role.OWNER, Membership.Role.MANAGER])
    if application.status not in {OnboardingApplication.Status.DRAFT, OnboardingApplication.Status.REVISION_REQUIRED}:
        raise ValidationError("Only draft or revision-required applications can be edited.")
    org = application.organization
    for field, value in organization_data.items():
        setattr(org, field, value)
    org.full_clean(exclude=["created_by"])
    org.save()
    profile = org.designer_profile if org.kind == Organization.Kind.DESIGNER else org.manufacturer_profile
    for field, value in profile_data.items():
        setattr(profile, field, value)
    profile.full_clean()
    profile.save()
    record_audit_event(actor=actor, action="onboarding.updated", instance=application, metadata={"organization_id": org.pk}, request=request)
    return application


@transaction.atomic
def add_or_update_member(*, organization, actor, user, role, request=None):
    require_org_access(actor, organization, roles=[Membership.Role.OWNER, Membership.Role.MANAGER])
    membership, _ = Membership.objects.get_or_create(organization=organization, user=user, defaults={"role": role, "is_active": True})
    membership.role = role
    membership.is_active = True
    membership.full_clean()
    membership.save()
    record_audit_event(actor=actor, action="business.member.upserted", instance=membership, metadata={"organization_id": organization.pk, "user_id": user.pk, "role": role}, request=request)
    return membership


@transaction.atomic
def deactivate_member(*, membership, actor, request=None):
    require_org_access(actor, membership.organization, roles=[Membership.Role.OWNER, Membership.Role.MANAGER])
    if membership.role == Membership.Role.OWNER:
        owner_count = Membership.objects.filter(organization=membership.organization, role=Membership.Role.OWNER, is_active=True).count()
        if owner_count <= 1:
            raise ValidationError("The last active owner cannot be removed.")
    membership.is_active = False
    membership.save(update_fields=["is_active"])
    record_audit_event(actor=actor, action="business.member.deactivated", instance=membership, metadata={"organization_id": membership.organization_id, "user_id": membership.user_id}, request=request)
    return membership
