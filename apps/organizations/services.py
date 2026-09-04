from copy import deepcopy
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit_event
from apps.notifications.models import Notification
from apps.platform_ops.models import ApplicationReviewConfiguration
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


def _lock_and_reject_duplicate_application(*, user, kind):
    user.__class__._default_manager.select_for_update().get(pk=user.pk)
    blocking_statuses = {
        OnboardingApplication.Status.DRAFT,
        OnboardingApplication.Status.SUBMITTED,
        OnboardingApplication.Status.REVISION_REQUIRED,
        OnboardingApplication.Status.APPROVED,
    }
    if OnboardingApplication.objects.filter(
        organization__created_by=user,
        organization__kind=kind,
        status__in=blocking_statuses,
    ).exists():
        role_label = "Designer" if kind == Organization.Kind.DESIGNER else "Manufacturer"
        raise ValidationError(
            f"A {role_label} application already exists for this account; V2-2 does not create duplicate resubmission records."
        )


def _split_requested_plan(profile_data):
    data = dict(profile_data)
    return data, data.pop("plan_policy_id", None)


def _persist_requested_plan(*, application, actor, plan_policy_id, request=None):
    if plan_policy_id in (None, ""):
        return None
    from apps.subscriptions.models import SubscriptionPlanPolicy
    from apps.subscriptions.services import set_onboarding_plan_selection

    try:
        policy = SubscriptionPlanPolicy.objects.get(pk=int(plan_policy_id))
    except (TypeError, ValueError, SubscriptionPlanPolicy.DoesNotExist) as exc:
        raise ValidationError("Selected onboarding plan is invalid.") from exc
    return set_onboarding_plan_selection(
        application=application,
        actor=actor,
        selected_plan_policy=policy,
        request=request,
    )


@transaction.atomic
def create_designer_onboarding(*, user, organization_data, profile_data, request=None):
    _lock_and_reject_duplicate_application(user=user, kind=Organization.Kind.DESIGNER)
    profile_data, plan_policy_id = _split_requested_plan(profile_data)
    org = Organization.objects.create(kind=Organization.Kind.DESIGNER, created_by=user, **organization_data)
    Membership.objects.create(organization=org, user=user, role=Membership.Role.OWNER)
    DesignerProfile.objects.create(organization=org, **profile_data)
    application = OnboardingApplication.objects.create(organization=org)
    _persist_requested_plan(application=application, actor=user, plan_policy_id=plan_policy_id, request=request)
    record_audit_event(actor=user, action="onboarding.designer.created", instance=application, metadata={"organization_id": org.pk}, request=request)
    return application


@transaction.atomic
def create_manufacturer_onboarding(*, user, organization_data, profile_data, request=None):
    _lock_and_reject_duplicate_application(user=user, kind=Organization.Kind.MANUFACTURER)
    profile_data, plan_policy_id = _split_requested_plan(profile_data)
    org = Organization.objects.create(kind=Organization.Kind.MANUFACTURER, created_by=user, **organization_data)
    Membership.objects.create(organization=org, user=user, role=Membership.Role.OWNER)
    ManufacturerProfile.objects.create(organization=org, **profile_data)
    application = OnboardingApplication.objects.create(organization=org)
    _persist_requested_plan(application=application, actor=user, plan_policy_id=plan_policy_id, request=request)
    record_audit_event(actor=user, action="onboarding.manufacturer.created", instance=application, metadata={"organization_id": org.pk}, request=request)
    return application


@transaction.atomic
def create_reapplication_from_rejected(*, application, actor, request=None):
    organization = application.organization
    if application.status != OnboardingApplication.Status.REJECTED:
        raise ValidationError("Only a final rejected application can start a new application attempt.")
    if organization.verification_status != Organization.VerificationStatus.REJECTED:
        raise ValidationError("The rejected application history is not in a valid final state.")
    require_org_access(actor, organization, roles=[Membership.Role.OWNER])
    if actor.pk != organization.created_by_id:
        raise PermissionDenied("Only the original application owner can start a new application attempt.")

    organization_data = {
        "display_name": organization.display_name,
        "legal_name": organization.legal_name,
        "email": organization.email,
        "phone": organization.phone,
        "website": organization.website,
        "address_line1": organization.address_line1,
        "address_line2": organization.address_line2,
        "city": organization.city,
        "region": organization.region,
        "country": organization.country,
    }
    if organization.kind == Organization.Kind.DESIGNER:
        profile = organization.designer_profile
        profile_data = {
            "studio_name": profile.studio_name,
            "portfolio_url": profile.portfolio_url,
            "social_links": deepcopy(profile.social_links or {}),
            "legal_registration_number": profile.legal_registration_number,
            "tax_number": profile.tax_number,
            "payout_information": profile.payout_information,
            "terms_accepted": profile.terms_accepted,
            "terms_accepted_at": profile.terms_accepted_at,
        }
        new_application = create_designer_onboarding(
            user=actor,
            organization_data=organization_data,
            profile_data=profile_data,
            request=request,
        )
    elif organization.kind == Organization.Kind.MANUFACTURER:
        profile = organization.manufacturer_profile
        profile_data = {
            "commercial_registration": profile.commercial_registration,
            "tax_number": profile.tax_number,
            "google_maps_url": profile.google_maps_url,
            "primary_contact_person": profile.primary_contact_person,
            "contact_job_title": profile.contact_job_title,
            "whatsapp": profile.whatsapp,
            "manufacturing_categories": deepcopy(profile.manufacturing_categories or []),
            "equipment": deepcopy(profile.equipment or []),
            "capability_summary": deepcopy(profile.capability_summary or {}),
            "daily_capacity": profile.daily_capacity,
            "monthly_capacity": profile.monthly_capacity,
            "certifications": deepcopy(profile.certifications or []),
            "payout_information": profile.payout_information,
            "terms_accepted": profile.terms_accepted,
            "terms_accepted_at": profile.terms_accepted_at,
        }
        new_application = create_manufacturer_onboarding(
            user=actor,
            organization_data=organization_data,
            profile_data=profile_data,
            request=request,
        )
    else:
        raise ValidationError("Professional reapplication requires a Designer or Manufacturer organization.")

    record_audit_event(
        actor=actor,
        action="onboarding.reapplication.created",
        instance=new_application,
        metadata={
            "previous_application_id": application.pk,
            "previous_organization_id": organization.pk,
            "new_organization_id": new_application.organization_id,
        },
        request=request,
    )
    return new_application


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
    from apps.subscriptions.services import ensure_onboarding_plan_selection

    ensure_onboarding_plan_selection(application=application, actor=actor, request=request)
    submitted_at = timezone.now()
    application.status = OnboardingApplication.Status.SUBMITTED
    application.submitted_at = submitted_at
    if application.initial_review_target_at is None:
        target_hours = ApplicationReviewConfiguration.current_initial_review_target_hours()
        application.initial_review_target_at = submitted_at + timedelta(hours=target_hours)
    application.reviewed_at = None
    application.reviewed_by = None
    application.save(update_fields=[
        "status",
        "submitted_at",
        "initial_review_target_at",
        "reviewed_at",
        "reviewed_by",
        "updated_at",
    ])
    application.organization.verification_status = Organization.VerificationStatus.PENDING
    application.organization.save(update_fields=["verification_status", "updated_at"])
    record_audit_event(actor=actor, action="onboarding.submitted", instance=application, metadata={"organization_id": application.organization_id}, request=request)
    return application


def _ensure_applicant_owner_membership(application):
    organization = application.organization
    membership, _ = Membership.objects.get_or_create(
        organization=organization,
        user=organization.created_by,
        defaults={"role": Membership.Role.OWNER, "is_active": True},
    )
    changed = []
    if membership.role != Membership.Role.OWNER:
        membership.role = Membership.Role.OWNER
        changed.append("role")
    if not membership.is_active:
        membership.is_active = True
        changed.append("is_active")
    if changed:
        membership.full_clean()
        membership.save(update_fields=changed)
    return membership


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
    applicant_membership = None
    if decision == OnboardingApplication.Status.REVISION_REQUIRED:
        application.revision_count += 1
        org_status = Organization.VerificationStatus.DRAFT
    elif decision == OnboardingApplication.Status.APPROVED:
        org_status = Organization.VerificationStatus.ACTIVE
        applicant_membership = _ensure_applicant_owner_membership(application)
    else:
        org_status = Organization.VerificationStatus.REJECTED

    application.save(update_fields=["status", "review_notes", "reviewed_by", "reviewed_at", "revision_count", "updated_at"])
    application.organization.verification_status = org_status
    application.organization.save(update_fields=["verification_status", "updated_at"])

    subscription = None
    selection = None
    if decision == OnboardingApplication.Status.APPROVED:
        from apps.subscriptions.services import (
            apply_approved_onboarding_plan_selection,
            ensure_subscription_for_organization,
        )
        from apps.subscriptions.team_services import reconcile_team_capacity_for_subscription

        subscription = ensure_subscription_for_organization(
            application.organization,
            activation_at=application.reviewed_at,
            actor=reviewer,
            request=request,
        )
        selection = apply_approved_onboarding_plan_selection(
            application=application,
            actor=reviewer,
            request=request,
        )
        reconcile_team_capacity_for_subscription(
            organization=application.organization,
            actor=reviewer,
            request=request,
        )

    title_en = {OnboardingApplication.Status.APPROVED: "Business application approved", OnboardingApplication.Status.REJECTED: "Business application rejected", OnboardingApplication.Status.REVISION_REQUIRED: "Business application needs revision"}[decision]
    title_ar = {OnboardingApplication.Status.APPROVED: "تمت الموافقة على طلب النشاط", OnboardingApplication.Status.REJECTED: "تم رفض طلب النشاط", OnboardingApplication.Status.REVISION_REQUIRED: "طلب النشاط يحتاج إلى تعديلات"}[decision]
    for membership in application.organization.memberships.filter(is_active=True).select_related("user"):
        Notification.objects.create(recipient=membership.user, type="business_onboarding_review", title_en=title_en, title_ar=title_ar, body_en=notes, body_ar=notes, destination="/designer/" if application.organization.kind == Organization.Kind.DESIGNER else "/manufacturer/")
    record_audit_event(
        actor=reviewer,
        action=f"onboarding.{decision}",
        instance=application,
        metadata={
            "organization_id": application.organization_id,
            "notes_present": bool(notes),
            "activated_membership_id": applicant_membership.pk if applicant_membership else None,
            "subscription_id": subscription.pk if subscription else None,
            "onboarding_plan_selection_id": selection.pk if selection else None,
        },
        request=request,
    )
    return application


@transaction.atomic
def update_onboarding(*, application, actor, organization_data, profile_data, request=None):
    require_org_access(actor, application.organization, roles=[Membership.Role.OWNER, Membership.Role.MANAGER])
    if application.status not in {OnboardingApplication.Status.DRAFT, OnboardingApplication.Status.REVISION_REQUIRED}:
        raise ValidationError("Only draft or revision-required applications can be edited.")
    profile_data, plan_policy_id = _split_requested_plan(profile_data)
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
    if plan_policy_id not in (None, ""):
        _persist_requested_plan(
            application=application,
            actor=actor,
            plan_policy_id=plan_policy_id,
            request=request,
        )
    record_audit_event(actor=actor, action="onboarding.updated", instance=application, metadata={"organization_id": org.pk}, request=request)
    return application


def _assert_non_owner_team_capacity(*, organization, user):
    target = Membership.objects.filter(organization=organization, user=user).first()
    if target and target.is_active and target.role != Membership.Role.OWNER:
        return
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        return
    from apps.subscriptions.services import entitlement_summary

    summary = entitlement_summary(organization)
    if summary["team_used"] >= summary["team_limit"]:
        raise ValidationError(f"The current plan allows {summary['team_limit']} active/pending subaccount seat(s).")


@transaction.atomic
def add_or_update_member(*, organization, actor, user, role, request=None):
    require_org_access(actor, organization, roles=[Membership.Role.OWNER, Membership.Role.MANAGER])
    if role != Membership.Role.OWNER:
        _assert_non_owner_team_capacity(organization=organization, user=user)
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
