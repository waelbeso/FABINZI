from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError

from apps.integrations.admin_site import fabinzi_admin_site
from .models import (
    Artwork,
    ArtworkAsset,
    ArtworkPlacement,
    ArtworkRegistrationCase,
    ArtworkRegistrationDocument,
    ArtworkRegistrationSource,
    ArtworkReview,
    ArtworkVersion,
    DesignedProduct,
    IPCase,
    IPCaseEvidence,
    IPDeclaration,
)
from .services import (
    moderate_ip_case,
    record_artwork_technical_check,
    review_artwork_version,
    transition_registration_case,
)


class ArtworkVersionInline(admin.TabularInline):
    model = ArtworkVersion
    extra = 0
    readonly_fields = (
        "symbolic_ref",
        "version_number",
        "status",
        "technical_check_status",
        "submitted_at",
        "reviewed_at",
        "reviewed_by",
    )
    fields = readonly_fields
    can_delete = False
    show_change_link = True


@admin.register(Artwork, site=fabinzi_admin_site)
class ArtworkAdmin(admin.ModelAdmin):
    list_display = ("title", "symbolic_ref", "organization", "status", "updated_at")
    list_filter = ("status", "organization")
    search_fields = ("title", "symbolic_ref", "organization__display_name")
    inlines = [ArtworkVersionInline]


@admin.register(ArtworkVersion, site=fabinzi_admin_site)
class ArtworkVersionAdmin(admin.ModelAdmin):
    list_display = ("artwork", "symbolic_ref", "version_number", "status", "technical_check_status", "submitted_at", "reviewed_at")
    list_filter = ("status", "technical_check_status")
    readonly_fields = (
        "submitted_at",
        "reviewed_at",
        "reviewed_by",
        "review_notes",
        "technical_check_status",
        "technical_check_result",
    )
    actions = [
        "technical_pass_selected",
        "technical_needs_evidence_selected",
        "technical_fail_selected",
        "approve_selected",
        "request_revision_selected",
        "reject_selected",
    ]

    def _require_change(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied("Artwork review permission required.")

    def _technical(self, request, queryset, status):
        self._require_change(request)
        count = 0
        for version in queryset:
            try:
                record_artwork_technical_check(
                    version=version,
                    reviewer=request.user,
                    status=status,
                    result={"source": "/Maneg/ V2-4 technical review action"},
                    request=request,
                )
                count += 1
            except (ValidationError, PermissionDenied) as exc:
                self.message_user(request, f"{version}: {exc}", level=messages.ERROR)
        if count:
            self.message_user(request, f"Recorded technical check for {count} Artwork Version(s).", level=messages.SUCCESS)

    @admin.action(description="Technical check PASS")
    def technical_pass_selected(self, request, queryset):
        self._technical(request, queryset, ArtworkVersion.TechnicalCheckStatus.PASS)

    @admin.action(description="Technical check needs evidence")
    def technical_needs_evidence_selected(self, request, queryset):
        self._technical(request, queryset, ArtworkVersion.TechnicalCheckStatus.NEEDS_EVIDENCE)

    @admin.action(description="Technical check FAIL")
    def technical_fail_selected(self, request, queryset):
        self._technical(request, queryset, ArtworkVersion.TechnicalCheckStatus.FAIL)

    def _review(self, request, queryset, decision):
        self._require_change(request)
        count = 0
        for version in queryset:
            try:
                review_artwork_version(
                    version=version,
                    reviewer=request.user,
                    decision=decision,
                    notes="Reviewed from FABINZI Control Center /Maneg/ V2-4.",
                    request=request,
                )
                count += 1
            except (ValidationError, PermissionDenied) as exc:
                self.message_user(request, f"{version}: {exc}", level=messages.ERROR)
        if count:
            self.message_user(request, f"Reviewed {count} Artwork Version(s).", level=messages.SUCCESS)

    @admin.action(description="Approve selected submitted Artwork Versions")
    def approve_selected(self, request, queryset):
        self._review(request, queryset, ArtworkReview.Decision.APPROVED)

    @admin.action(description="Request revision for selected submitted Artwork Versions")
    def request_revision_selected(self, request, queryset):
        self._review(request, queryset, ArtworkReview.Decision.REVISION_REQUIRED)

    @admin.action(description="Reject selected submitted Artwork Versions")
    def reject_selected(self, request, queryset):
        self._review(request, queryset, ArtworkReview.Decision.REJECTED)


@admin.register(ArtworkRegistrationSource, site=fabinzi_admin_site)
class ArtworkRegistrationSourceAdmin(admin.ModelAdmin):
    list_display = ("source_name", "source_version", "source_filename", "visual_graphic_applicability_confirmed", "is_active")
    list_filter = ("visual_graphic_applicability_confirmed", "is_active")
    search_fields = ("source_name", "source_filename", "source_sha256", "scope_description")

    def get_readonly_fields(self, request, obj=None):
        if not obj:
            return ("created_at",)
        frozen = (
            "source_name",
            "source_kind",
            "source_filename",
            "source_sha256",
            "source_version",
            "source_date",
            "scope_description",
            "visual_graphic_applicability_confirmed",
            "field_schema",
            "procedure_facts",
            "source_limitations",
            "created_at",
        )
        return frozen


@admin.register(ArtworkRegistrationCase, site=fabinzi_admin_site)
class ArtworkRegistrationCaseAdmin(admin.ModelAdmin):
    list_display = ("id", "artwork_version", "applicant", "status", "source_snapshot", "service_price_egp", "updated_at")
    list_filter = ("status", "source_applicability_confirmed_for_case")
    search_fields = ("artwork_version__artwork__title", "applicant__username", "external_reference")
    readonly_fields = (
        "artwork_version",
        "applicant",
        "source_snapshot",
        "procedure_template_key",
        "captured_data",
        "representation_state",
        "service_price_egp",
        "official_fee_information",
        "status",
        "source_applicability_confirmed_for_case",
        "external_reference",
        "external_submitted_at",
        "completed_at",
        "reviewed_by",
        "created_at",
        "updated_at",
    )
    actions = ("needs_evidence_selected", "staff_review_selected", "reject_selected", "cancel_selected")

    def has_add_permission(self, request):
        return False

    def _transition(self, request, queryset, target):
        if not self.has_change_permission(request):
            raise PermissionDenied("Artwork Registration review permission required.")
        count = 0
        for case in queryset:
            try:
                transition_registration_case(
                    case=case,
                    reviewer=request.user,
                    status=target,
                    notes="Operational transition recorded from /Maneg/ V2-4.",
                    request=request,
                )
                count += 1
            except (ValidationError, PermissionDenied) as exc:
                self.message_user(request, f"Case {case.pk}: {exc}", level=messages.ERROR)
        if count:
            self.message_user(request, f"Transitioned {count} registration case(s).", level=messages.SUCCESS)

    @admin.action(description="Mark evidence required")
    def needs_evidence_selected(self, request, queryset):
        self._transition(request, queryset, ArtworkRegistrationCase.Status.EVIDENCE_REQUIRED)

    @admin.action(description="Move to staff review")
    def staff_review_selected(self, request, queryset):
        self._transition(request, queryset, ArtworkRegistrationCase.Status.STAFF_REVIEW)

    @admin.action(description="Reject registration case")
    def reject_selected(self, request, queryset):
        self._transition(request, queryset, ArtworkRegistrationCase.Status.REJECTED)

    @admin.action(description="Cancel registration case")
    def cancel_selected(self, request, queryset):
        self._transition(request, queryset, ArtworkRegistrationCase.Status.CANCELLED)


@admin.register(DesignedProduct, site=fabinzi_admin_site)
class DesignedProductAdmin(admin.ModelAdmin):
    list_display = ("title", "symbolic_ref", "organization", "status", "reference_only", "updated_at")
    list_filter = ("status", "reference_only", "organization")
    search_fields = ("title", "symbolic_ref", "organization__display_name")
    readonly_fields = ("garment_creator_organization", "artwork_creator_organization", "economic_attribution", "reference_only")


@admin.register(IPCase, site=fabinzi_admin_site)
class IPCaseAdmin(admin.ModelAdmin):
    list_display = ("id", "artwork", "designed_product", "reporter_email", "status", "resolution", "created_at")
    list_filter = ("status", "resolution")
    search_fields = ("reporter_name", "reporter_email", "allegation", "claimant_rights")
    readonly_fields = ("created_by", "created_at", "updated_at", "resolved_at")
    actions = ["takedown_selected", "dismiss_selected"]

    @admin.action(description="Resolve selected cases with takedown")
    def takedown_selected(self, request, queryset):
        if not self.has_change_permission(request):
            raise PermissionDenied("IP moderation permission required.")
        for case in queryset:
            moderate_ip_case(
                case=case,
                reviewer=request.user,
                status=IPCase.Status.RESOLVED,
                resolution=IPCase.Resolution.TAKEDOWN,
                notes="Takedown via Control Center",
                request=request,
            )

    @admin.action(description="Dismiss selected claims")
    def dismiss_selected(self, request, queryset):
        if not self.has_change_permission(request):
            raise PermissionDenied("IP moderation permission required.")
        for case in queryset:
            moderate_ip_case(
                case=case,
                reviewer=request.user,
                status=IPCase.Status.DISMISSED,
                resolution=IPCase.Resolution.CLAIM_REJECTED,
                notes="Claim dismissed via Control Center",
                request=request,
            )


for model in (
    ArtworkAsset,
    ArtworkPlacement,
    ArtworkReview,
    IPDeclaration,
    IPCaseEvidence,
    ArtworkRegistrationDocument,
):
    try:
        fabinzi_admin_site.register(model)
    except admin.sites.AlreadyRegistered:
        pass
