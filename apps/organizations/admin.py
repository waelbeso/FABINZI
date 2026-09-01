from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect
from django.urls import path, reverse

from apps.integrations.admin_site import fabinzi_admin_site
from .models import (
    DesignerProfile,
    ManufacturerProfile,
    Membership,
    OnboardingApplication,
    Organization,
    PublicProfileRevision,
    VerificationDocument,
)
from .public_profile_services import review_public_profile_revision, start_public_profile_review
from .services import review_application


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    readonly_fields = ("joined_at",)


@admin.register(Organization, site=fabinzi_admin_site)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("display_name", "kind", "verification_status", "email", "country", "updated_at")
    list_filter = ("kind", "verification_status", "country")
    search_fields = ("display_name", "legal_name", "email")
    readonly_fields = ("verification_status", "created_by", "created_at", "updated_at")
    inlines = [MembershipInline]


@admin.register(DesignerProfile, site=fabinzi_admin_site)
class DesignerProfileAdmin(admin.ModelAdmin):
    list_display = ("organization", "studio_name", "terms_accepted")
    search_fields = ("organization__display_name", "studio_name")


@admin.register(ManufacturerProfile, site=fabinzi_admin_site)
class ManufacturerProfileAdmin(admin.ModelAdmin):
    list_display = ("organization", "commercial_registration", "daily_capacity", "monthly_capacity", "terms_accepted")
    search_fields = ("organization__display_name", "commercial_registration")


class VerificationDocumentInline(admin.TabularInline):
    model = VerificationDocument
    extra = 0


@admin.register(OnboardingApplication, site=fabinzi_admin_site)
class OnboardingApplicationAdmin(admin.ModelAdmin):
    list_display = ("organization", "status", "review_target_at", "revision_count", "submitted_at", "reviewed_at", "reviewed_by")
    list_filter = ("status", "organization__kind")
    search_fields = ("organization__display_name", "organization__legal_name", "organization__email")
    readonly_fields = (
        "status",
        "review_notes",
        "revision_count",
        "submitted_at",
        "initial_review_target_at",
        "reviewed_at",
        "reviewed_by",
        "created_at",
        "updated_at",
    )
    inlines = [VerificationDocumentInline]
    change_form_template = "admin/organizations/onboardingapplication/change_form.html"

    def get_urls(self):
        custom = [
            path("<int:object_id>/approve/", self.admin_site.admin_view(self.review_view), {"decision": "approved"}, name="organizations_onboardingapplication_approve"),
            path("<int:object_id>/revision/", self.admin_site.admin_view(self.review_view), {"decision": "revision_required"}, name="organizations_onboardingapplication_revision"),
            path("<int:object_id>/reject/", self.admin_site.admin_view(self.review_view), {"decision": "rejected"}, name="organizations_onboardingapplication_reject"),
        ]
        return custom + super().get_urls()

    def review_view(self, request, object_id, decision):
        application = self.get_object(request, object_id)
        if application is None:
            self.message_user(request, "Application not found.", messages.ERROR)
            return HttpResponseRedirect(reverse("fabinzi_admin:organizations_onboardingapplication_changelist"))
        if not self.has_change_permission(request, application):
            raise PermissionDenied("Application review permission required.")
        if request.method == "POST":
            notes = request.POST.get("review_notes", "").strip()
            try:
                review_application(application=application, reviewer=request.user, decision=decision, notes=notes, request=request)
            except ValidationError as exc:
                self.message_user(request, "; ".join(exc.messages), messages.ERROR)
            else:
                self.message_user(request, f"Application marked {decision.replace('_', ' ')}.", messages.SUCCESS)
            return HttpResponseRedirect(reverse("fabinzi_admin:organizations_onboardingapplication_change", args=[application.pk]))
        self.message_user(request, "Review actions require POST.", messages.ERROR)
        return HttpResponseRedirect(reverse("fabinzi_admin:organizations_onboardingapplication_change", args=[application.pk]))


@admin.register(PublicProfileRevision, site=fabinzi_admin_site)
class PublicProfileRevisionAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "status",
        "created_by",
        "submitted_at",
        "reviewed_at",
        "reviewed_by",
    )
    list_filter = ("status", "organization__kind")
    search_fields = (
        "organization__display_name",
        "organization__legal_name",
        "created_by__username",
        "created_by__email",
    )
    readonly_fields = (
        "organization",
        "status",
        "proposed_data",
        "created_by",
        "submitted_at",
        "reviewed_at",
        "reviewed_by",
        "review_notes",
        "created_at",
        "updated_at",
    )
    change_form_template = "admin/organizations/publicprofilerevision/change_form.html"

    def get_urls(self):
        custom = [
            path(
                "<int:object_id>/start-review/",
                self.admin_site.admin_view(self.start_review_view),
                name="organizations_publicprofilerevision_start_review",
            ),
            path(
                "<int:object_id>/approve/",
                self.admin_site.admin_view(self.review_view),
                {"decision": PublicProfileRevision.Status.APPROVED},
                name="organizations_publicprofilerevision_approve",
            ),
            path(
                "<int:object_id>/changes-required/",
                self.admin_site.admin_view(self.review_view),
                {"decision": PublicProfileRevision.Status.CHANGES_REQUIRED},
                name="organizations_publicprofilerevision_changes_required",
            ),
            path(
                "<int:object_id>/reject/",
                self.admin_site.admin_view(self.review_view),
                {"decision": PublicProfileRevision.Status.REJECTED},
                name="organizations_publicprofilerevision_reject",
            ),
        ]
        return custom + super().get_urls()

    def _revision_or_redirect(self, request, object_id):
        revision = self.get_object(request, object_id)
        if revision is None:
            self.message_user(request, "Public profile revision not found.", messages.ERROR)
            return None, HttpResponseRedirect(
                reverse("fabinzi_admin:organizations_publicprofilerevision_changelist")
            )
        if not self.has_change_permission(request, revision):
            raise PermissionDenied("Public profile review permission required.")
        return revision, None

    def start_review_view(self, request, object_id):
        revision, response = self._revision_or_redirect(request, object_id)
        if response:
            return response
        if request.method != "POST":
            self.message_user(request, "Review actions require POST.", messages.ERROR)
        else:
            try:
                start_public_profile_review(
                    revision=revision,
                    reviewer=request.user,
                    request=request,
                )
            except ValidationError as exc:
                self.message_user(request, "; ".join(exc.messages), messages.ERROR)
            else:
                self.message_user(request, "Public profile review started.", messages.SUCCESS)
        return HttpResponseRedirect(
            reverse(
                "fabinzi_admin:organizations_publicprofilerevision_change",
                args=[revision.pk],
            )
        )

    def review_view(self, request, object_id, decision):
        revision, response = self._revision_or_redirect(request, object_id)
        if response:
            return response
        if request.method != "POST":
            self.message_user(request, "Review actions require POST.", messages.ERROR)
            return HttpResponseRedirect(
                reverse(
                    "fabinzi_admin:organizations_publicprofilerevision_change",
                    args=[revision.pk],
                )
            )
        try:
            review_public_profile_revision(
                revision=revision,
                reviewer=request.user,
                decision=decision,
                notes=request.POST.get("review_notes", "").strip(),
                request=request,
            )
        except ValidationError as exc:
            self.message_user(request, "; ".join(exc.messages), messages.ERROR)
        else:
            self.message_user(
                request,
                f"Public profile revision marked {decision}.",
                messages.SUCCESS,
            )
        return HttpResponseRedirect(
            reverse(
                "fabinzi_admin:organizations_publicprofilerevision_change",
                args=[revision.pk],
            )
        )


@admin.register(Membership, site=fabinzi_admin_site)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("organization", "user", "role", "is_active", "joined_at")
    list_filter = ("role", "is_active", "organization__kind")
    search_fields = ("organization__display_name", "user__username", "user__email")
