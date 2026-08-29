from django.contrib import admin
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.urls import path, reverse

from apps.audit.services import record_audit_event
from apps.integrations.admin_site import fabinzi_admin_site
from .models import Artwork, ArtworkAsset, ArtworkPlacement, ArtworkReview, ArtworkVersion, DesignedProduct, IPCase, IPCaseEvidence, IPDeclaration
from .services import moderate_ip_case, review_artwork_version


class ArtworkVersionInline(admin.TabularInline):
    model = ArtworkVersion
    extra = 0
    readonly_fields = ("version_number","status","submitted_at","reviewed_at","reviewed_by")


@admin.register(Artwork, site=fabinzi_admin_site)
class ArtworkAdmin(admin.ModelAdmin):
    list_display = ("title","organization","status","updated_at")
    list_filter = ("status","organization")
    search_fields = ("title","organization__display_name")
    inlines = [ArtworkVersionInline]


@admin.register(ArtworkVersion, site=fabinzi_admin_site)
class ArtworkVersionAdmin(admin.ModelAdmin):
    list_display = ("artwork","version_number","status","submitted_at","reviewed_at")
    list_filter = ("status",)
    readonly_fields = ("submitted_at","reviewed_at","reviewed_by","review_notes")
    actions = ["approve_selected","request_revision_selected","reject_selected"]
    def _review(self, request, queryset, decision):
        count = 0
        for version in queryset:
            try: review_artwork_version(version=version, reviewer=request.user, decision=decision, notes="Reviewed from FABINZI Control Center", request=request); count += 1
            except ValidationError: continue
        self.message_user(request, f"Reviewed {count} Artwork Version(s).")
    @admin.action(description="Approve selected submitted Artwork Versions")
    def approve_selected(self, request, queryset): self._review(request, queryset, ArtworkReview.Decision.APPROVED)
    @admin.action(description="Request revision for selected submitted Artwork Versions")
    def request_revision_selected(self, request, queryset): self._review(request, queryset, ArtworkReview.Decision.REVISION_REQUIRED)
    @admin.action(description="Reject selected submitted Artwork Versions")
    def reject_selected(self, request, queryset): self._review(request, queryset, ArtworkReview.Decision.REJECTED)


@admin.register(DesignedProduct, site=fabinzi_admin_site)
class DesignedProductAdmin(admin.ModelAdmin):
    list_display = ("title","organization","status","updated_at")
    list_filter = ("status","organization")
    search_fields = ("title","organization__display_name")


@admin.register(IPCase, site=fabinzi_admin_site)
class IPCaseAdmin(admin.ModelAdmin):
    list_display = ("id","artwork","designed_product","reporter_email","status","resolution","created_at")
    list_filter = ("status","resolution")
    search_fields = ("reporter_name","reporter_email","allegation","claimant_rights")
    readonly_fields = ("created_by","created_at","updated_at","resolved_at")
    actions = ["takedown_selected","dismiss_selected"]
    @admin.action(description="Resolve selected cases with takedown")
    def takedown_selected(self, request, queryset):
        for case in queryset: moderate_ip_case(case=case, reviewer=request.user, status=IPCase.Status.RESOLVED, resolution=IPCase.Resolution.TAKEDOWN, notes="Takedown via Control Center", request=request)
    @admin.action(description="Dismiss selected claims")
    def dismiss_selected(self, request, queryset):
        for case in queryset: moderate_ip_case(case=case, reviewer=request.user, status=IPCase.Status.DISMISSED, resolution=IPCase.Resolution.CLAIM_REJECTED, notes="Claim dismissed via Control Center", request=request)


for model in (ArtworkAsset, ArtworkPlacement, ArtworkReview, IPDeclaration, IPCaseEvidence):
    try: fabinzi_admin_site.register(model)
    except admin.sites.AlreadyRegistered: pass
