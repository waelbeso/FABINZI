from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError

from apps.integrations.admin_site import fabinzi_admin_site
from .models import (
    DecorationZone,
    DesignAsset,
    DesignColorway,
    DesignColorwayImage,
    DesignMaterial,
    DesignPOMValue,
    DesignPatternRequirement,
    DesignPointOfMeasure,
    DesignReferenceProvenance,
    GarmentDesign,
    GarmentDesignVersion,
    ReferenceDataset,
    ReferencePackage,
    SizeChartRow,
    TechnicalBlocker,
    TechnicalReview,
)
from .services import review_version, set_production_engineering_validation, technical_completeness


class VersionInline(admin.TabularInline):
    model = GarmentDesignVersion
    extra = 0
    readonly_fields = (
        "symbolic_ref",
        "version_number",
        "status",
        "submitted_at",
        "reviewed_at",
        "reviewed_by",
        "production_engineering_validated",
    )
    fields = readonly_fields
    can_delete = False
    show_change_link = True


@admin.register(GarmentDesign, site=fabinzi_admin_site)
class GarmentDesignAdmin(admin.ModelAdmin):
    list_display = ("title", "symbolic_ref", "organization", "status", "updated_at")
    list_filter = ("status", "organization")
    search_fields = ("title", "symbolic_ref", "organization__display_name")
    readonly_fields = ("symbolic_ref", "created_by", "created_at", "updated_at")
    inlines = [VersionInline]


def _run_review_action(modeladmin, request, queryset, decision):
    if not modeladmin.has_change_permission(request):
        raise PermissionDenied("Technical review permission required.")
    changed = 0
    for version in queryset:
        try:
            review_version(
                version=version,
                reviewer=request.user,
                decision=decision,
                notes="Decision recorded from /Maneg/ V2-4 technical review action.",
                request=request,
            )
            changed += 1
        except (ValidationError, PermissionDenied) as exc:
            modeladmin.message_user(request, f"{version}: {exc}", level=messages.ERROR)
    if changed:
        modeladmin.message_user(request, f"Reviewed {changed} Garment Design Version(s).", level=messages.SUCCESS)


@admin.register(GarmentDesignVersion, site=fabinzi_admin_site)
class GarmentDesignVersionAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "symbolic_ref",
        "status",
        "product_class",
        "size_system",
        "technical_complete",
        "production_engineering_validated",
    )
    list_filter = (
        "status",
        "product_class",
        "size_system",
        "decoration_applicability",
        "production_engineering_validated",
    )
    search_fields = ("symbolic_ref", "design__symbolic_ref", "design__title", "design__organization__display_name")
    readonly_fields = (
        "design",
        "symbolic_ref",
        "version_number",
        "status",
        "created_by",
        "created_at",
        "submitted_at",
        "reviewed_at",
        "reviewed_by",
        "review_notes",
        "production_engineering_validated",
        "production_engineering_notes",
    )
    actions = ("approve_technical", "require_revision", "reject_technical", "validate_production_engineering", "revoke_production_engineering")

    @admin.display(boolean=True, description="Technical complete")
    def technical_complete(self, obj):
        return technical_completeness(obj)["complete"]

    @admin.action(description="Approve submitted technical version")
    def approve_technical(self, request, queryset):
        _run_review_action(self, request, queryset, TechnicalReview.Decision.APPROVED)

    @admin.action(description="Require technical revision")
    def require_revision(self, request, queryset):
        _run_review_action(self, request, queryset, TechnicalReview.Decision.REVISION_REQUIRED)

    @admin.action(description="Reject submitted technical version")
    def reject_technical(self, request, queryset):
        _run_review_action(self, request, queryset, TechnicalReview.Decision.REJECTED)

    @admin.action(description="Validate production engineering for approved real version")
    def validate_production_engineering(self, request, queryset):
        if not self.has_change_permission(request):
            raise PermissionDenied("Technical review permission required.")
        changed = 0
        for version in queryset:
            try:
                set_production_engineering_validation(
                    version=version,
                    reviewer=request.user,
                    validated=True,
                    notes="Production engineering validation recorded from /Maneg/.",
                    request=request,
                )
                changed += 1
            except (ValidationError, PermissionDenied) as exc:
                self.message_user(request, f"{version}: {exc}", level=messages.ERROR)
        if changed:
            self.message_user(request, f"Production-engineering validated {changed} version(s).", level=messages.SUCCESS)

    @admin.action(description="Revoke production engineering validation")
    def revoke_production_engineering(self, request, queryset):
        if not self.has_change_permission(request):
            raise PermissionDenied("Technical review permission required.")
        for version in queryset:
            set_production_engineering_validation(
                version=version,
                reviewer=request.user,
                validated=False,
                notes="Production engineering validation revoked from /Maneg/.",
                request=request,
            )


@admin.register(TechnicalBlocker, site=fabinzi_admin_site)
class TechnicalBlockerAdmin(admin.ModelAdmin):
    list_display = ("code", "version", "status", "reference_only", "created_at")
    list_filter = ("status", "reference_only")
    search_fields = ("code", "description", "version__symbolic_ref", "version__design__title")
    readonly_fields = ("created_at", "resolved_at", "resolved_by")


@admin.register(ReferenceDataset, site=fabinzi_admin_site)
class ReferenceDatasetAdmin(admin.ModelAdmin):
    list_display = ("dataset_name", "dataset_version", "created_at")
    search_fields = ("dataset_name", "dataset_version")

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return tuple(field.name for field in self.model._meta.fields)
        return ("created_at",)


@admin.register(ReferencePackage, site=fabinzi_admin_site)
class ReferencePackageAdmin(admin.ModelAdmin):
    list_display = ("product_ref", "canonical_filename", "status", "public_reference_allowed", "production_engineering_validated")
    list_filter = ("status", "golden_reference_complete", "public_reference_allowed", "production_engineering_validated")
    search_fields = ("product_ref", "canonical_filename", "package_sha256", "source_design_ref", "source_gdv_ref")
    readonly_fields = tuple(field.name for field in ReferencePackage._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DesignReferenceProvenance, site=fabinzi_admin_site)
class DesignReferenceProvenanceAdmin(admin.ModelAdmin):
    list_display = ("package", "design", "version", "import_implementation_version", "imported_at")
    search_fields = ("package__product_ref", "design__symbolic_ref", "version__symbolic_ref")
    readonly_fields = tuple(field.name for field in DesignReferenceProvenance._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


for model in (
    SizeChartRow,
    DesignPointOfMeasure,
    DesignPOMValue,
    DesignMaterial,
    DesignPatternRequirement,
    DesignColorway,
    DesignColorwayImage,
    DecorationZone,
    DesignAsset,
    TechnicalReview,
):
    try:
        fabinzi_admin_site.register(model)
    except admin.sites.AlreadyRegistered:
        pass
