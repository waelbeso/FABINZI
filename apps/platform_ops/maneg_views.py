from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.artwork.models import (
    ArtworkAsset,
    ArtworkReview,
    ArtworkVersion,
    DesignedProduct,
    IPCase,
    IPCaseEvidence,
)
from apps.artwork.services import moderate_ip_case, review_artwork_version
from apps.audit.models import AuditEvent
from apps.checkout.models import CustomerOrder, CustomerPurchase, PaymentAttempt
from apps.design.models import DesignAsset, GarmentDesignVersion, TechnicalReview
from apps.design.services import review_version
from apps.finance.models import FinanceAccount, OrderFinance, PayoutProfile, SettlementRequest
from apps.finance.services import account_balance, mark_settlement_paid, review_payout_profile, review_settlement
from apps.integrations.forms import IntegrationConfigAdminForm
from apps.integrations.models import IntegrationConfig
from apps.manufacturer_marketplace.models import ManufacturerListing
from apps.media.services import private_media_response
from apps.notifications.models import NotificationDelivery, NotificationPreference
from apps.operations.models import FulfillmentRecord, ProductionJob
from apps.organizations.models import Membership, OnboardingApplication, Organization, VerificationDocument
from apps.organizations.services import review_application
from apps.storefront.models import StoreProduct, Storefront

from .maneg_forms import MaintenanceWindowForm, PlatformAnnouncementForm
from .maneg_services import (
    reactivate_organization,
    run_integration_test,
    save_announcement,
    save_integration_config,
    save_maintenance,
    suspend_organization,
    suspend_user,
)
from .models import MaintenanceWindow, PlatformAnnouncement

User = get_user_model()


NAV = (
    ("overview", "Overview", "نظرة عامة", "fabinzi_admin:index", None),
    ("users", "Users", "المستخدمون", "fabinzi_admin:maneg-users", "accounts.view_user"),
    ("organizations", "Organizations", "المنظمات", "fabinzi_admin:maneg-organizations", "organizations.view_organization"),
    ("verification", "Verification", "التحقق والمراجعة", "fabinzi_admin:maneg-verification", "organizations.view_onboardingapplication"),
    ("designs", "Garment Designs", "تصاميم القطع", "fabinzi_admin:maneg-design-review", "design.view_garmentdesignversion"),
    ("artwork", "Artwork / IP", "الأعمال الفنية / الحقوق", "fabinzi_admin:maneg-artwork-ip", "artwork.view_artworkversion|artwork.view_ipcase"),
    ("catalog", "Catalog / Store", "المتجر / الكتالوج", "fabinzi_admin:maneg-catalog", "storefront.view_storefront|storefront.view_storeproduct"),
    ("orders", "Purchases / Orders", "المشتريات / الطلبات", "fabinzi_admin:maneg-orders", "checkout.view_customerpurchase|checkout.view_customerorder"),
    ("production", "Production / Fulfillment", "الإنتاج / التنفيذ", "fabinzi_admin:maneg-production", "operations.view_productionjob|operations.view_fulfillmentrecord"),
    ("finance", "Finance / Settlements", "المالية / التسويات", "fabinzi_admin:maneg-finance", "finance.view_financeaccount|finance.view_settlementrequest"),
    ("notifications", "Notifications", "الإشعارات", "fabinzi_admin:maneg-notifications", "notifications.view_notificationdelivery"),
    ("integrations", "Integrations", "التكاملات", "fabinzi_admin:maneg-integrations", "integrations.view_integrationconfig"),
    ("announcements", "Announcement", "الإعلان", "fabinzi_admin:maneg-announcements", "platform_ops.view_platformannouncement"),
    ("maintenance", "Maintenance", "وضع الصيانة", "fabinzi_admin:maneg-maintenance", "platform_ops.view_maintenancewindow"),
    ("audit", "Audit Log", "سجل التدقيق", "fabinzi_admin:maneg-audit", "audit.view_auditevent"),
)


def _has(user, expression):
    if not expression:
        return True
    return any(user.has_perm(part) for part in expression.split("|"))


def _require(request, *permissions, any_of=False):
    checks = [request.user.has_perm(permission) for permission in permissions]
    allowed = any(checks) if any_of else all(checks)
    if not allowed:
        raise PermissionDenied("Your staff account does not have permission for this Control Center operation.")


def _lang(request):
    return "ar" if getattr(request, "LANGUAGE_CODE", "en").startswith("ar") else "en"


def _text(request, en, ar):
    return ar if _lang(request) == "ar" else en


def _context(request, *, section, title_en, title_ar, **extra):
    language = _lang(request)
    nav = []
    for key, en, ar, route, permission in NAV:
        if _has(request.user, permission):
            nav.append({"key": key, "label": ar if language == "ar" else en, "url": reverse(route)})
    if request.user.is_superuser:
        nav.append({"key": "system", "label": "حالة النظام" if language == "ar" else "System / Security", "url": reverse("fabinzi_admin:maneg-system")})
    nav.append({"key": "expert", "label": "Django Admin" if language == "en" else "إدارة Django المتقدمة", "url": reverse("fabinzi_admin:maneg-expert")})
    context = {
        "maneg_section": section,
        "maneg_title": title_ar if language == "ar" else title_en,
        "maneg_nav": nav,
        "maneg_language": language,
        "maneg_is_ar": language == "ar",
    }
    context.update(extra)
    return context


def _render(request, template, **context):
    response = render(request, template, context)
    response["Cache-Control"] = "private, no-store"
    return response


def _q(request):
    return request.GET.get("q", "").strip()[:120]


def _mfa_configured(user):
    return TOTPDevice.objects.filter(user=user, confirmed=True).exists() or StaticDevice.objects.filter(user=user).exists()


def dashboard(request, extra_context=None):
    metrics = []
    if request.user.has_perm("organizations.view_onboardingapplication"):
        metrics.append({"label_en": "Pending verification", "label_ar": "طلبات تحقق معلقة", "value": OnboardingApplication.objects.filter(status=OnboardingApplication.Status.SUBMITTED).count(), "url": reverse("fabinzi_admin:maneg-verification")})
    if request.user.has_perm("design.view_garmentdesignversion"):
        metrics.append({"label_en": "Designs awaiting review", "label_ar": "تصاميم بانتظار المراجعة", "value": GarmentDesignVersion.objects.filter(status=GarmentDesignVersion.Status.SUBMITTED).count(), "url": reverse("fabinzi_admin:maneg-design-review")})
    if request.user.has_perm("artwork.view_artworkversion"):
        metrics.append({"label_en": "Artwork awaiting review", "label_ar": "أعمال فنية بانتظار المراجعة", "value": ArtworkVersion.objects.filter(status=ArtworkVersion.Status.SUBMITTED).count(), "url": reverse("fabinzi_admin:maneg-artwork-ip")})
    if request.user.has_perm("artwork.view_ipcase"):
        metrics.append({"label_en": "Open IP cases", "label_ar": "قضايا حقوق مفتوحة", "value": IPCase.objects.filter(status__in=[IPCase.Status.OPEN, IPCase.Status.UNDER_REVIEW, IPCase.Status.ACTION_REQUIRED]).count(), "url": reverse("fabinzi_admin:maneg-artwork-ip")})
    if request.user.has_perm("operations.view_productionjob"):
        metrics.append({"label_en": "Production attention", "label_ar": "إنتاج يحتاج متابعة", "value": ProductionJob.objects.filter(status__in=[ProductionJob.Status.QC_FAILED, ProductionJob.Status.AWAITING_ASSIGNMENT]).count(), "url": reverse("fabinzi_admin:maneg-production")})
    if request.user.has_perm("operations.view_fulfillmentrecord"):
        metrics.append({"label_en": "Fulfillment exceptions", "label_ar": "استثناءات التنفيذ", "value": FulfillmentRecord.objects.filter(status__in=[FulfillmentRecord.Status.FAILED, FulfillmentRecord.Status.RETURNED]).count(), "url": reverse("fabinzi_admin:maneg-production")})
    if request.user.has_perm("finance.view_settlementrequest"):
        metrics.append({"label_en": "Pending settlements", "label_ar": "تسويات معلقة", "value": SettlementRequest.objects.filter(status=SettlementRequest.Status.REQUESTED).count(), "url": reverse("fabinzi_admin:maneg-finance")})
    integration_summary = None
    if request.user.has_perm("integrations.view_integrationconfig"):
        integration_summary = {
            "enabled": IntegrationConfig.objects.filter(enabled=True).count(),
            "failed": IntegrationConfig.objects.filter(last_test_status=IntegrationConfig.TestStatus.FAILURE).count(),
            "never": IntegrationConfig.objects.filter(last_test_status=IntegrationConfig.TestStatus.NEVER).count(),
        }
    announcement = PlatformAnnouncement.active().first() if request.user.has_perm("platform_ops.view_platformannouncement") else None
    maintenance = MaintenanceWindow.current() if request.user.has_perm("platform_ops.view_maintenancewindow") else None
    context = _context(request, section="overview", title_en="Control Center", title_ar="مركز التحكم", metrics=metrics, integration_summary=integration_summary, current_announcement=announcement, current_maintenance=maintenance)
    if extra_context:
        context.update(extra_context)
    return _render(request, "maneg/dashboard.html", **context)


def users(request):
    _require(request, "accounts.view_user")
    if request.method == "POST":
        _require(request, "accounts.change_user")
        target = get_object_or_404(User, pk=request.POST.get("user_id"))
        if request.POST.get("action") != "suspend":
            raise ValidationError("Unsupported user action.")
        try:
            suspend_user(target=target, actor=request.user, request=request)
            messages.success(request, _text(request, "User suspended and audit event recorded.", "تم إيقاف المستخدم وتسجيل العملية."))
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
        return HttpResponseRedirect(reverse("fabinzi_admin:maneg-users"))
    qs = User.objects.all().order_by("-date_joined", "id")
    query = _q(request)
    if query:
        qs = qs.filter(Q(username__icontains=query) | Q(email__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query))
    state = request.GET.get("state", "")
    if state == "active": qs = qs.filter(is_active=True)
    elif state == "inactive": qs = qs.filter(is_active=False)
    elif state == "staff": qs = qs.filter(is_staff=True)
    rows = list(qs[:100])
    for row in rows:
        row.maneg_mfa = _mfa_configured(row)
    return _render(request, "maneg/users.html", **_context(request, section="users", title_en="Users", title_ar="المستخدمون", users=rows, query=query, state=state))


def user_detail(request, pk):
    _require(request, "accounts.view_user")
    target = get_object_or_404(User, pk=pk)
    memberships = target.business_memberships.select_related("organization").order_by("organization__display_name") if request.user.has_perm("organizations.view_membership") else []
    events = AuditEvent.objects.filter(Q(actor=target) | Q(object_type="accounts.User", object_id=str(target.pk))).select_related("actor")[:50] if request.user.has_perm("audit.view_auditevent") else []
    return _render(request, "maneg/user_detail.html", **_context(request, section="users", title_en="User account", title_ar="حساب المستخدم", target=target, memberships=memberships, mfa_configured=_mfa_configured(target), audit_events=events))


def organizations(request):
    _require(request, "organizations.view_organization")
    qs = Organization.objects.select_related("onboarding_application").order_by("-updated_at")
    query = _q(request)
    if query:
        qs = qs.filter(Q(display_name__icontains=query) | Q(legal_name__icontains=query) | Q(email__icontains=query))
    kind = request.GET.get("kind", "")
    status = request.GET.get("status", "")
    if kind in dict(Organization.Kind.choices): qs = qs.filter(kind=kind)
    if status in dict(Organization.VerificationStatus.choices): qs = qs.filter(verification_status=status)
    return _render(request, "maneg/organizations.html", **_context(request, section="organizations", title_en="Organizations", title_ar="المنظمات", organizations=qs[:100], query=query, kind=kind, status=status))


def organization_detail(request, pk):
    _require(request, "organizations.view_organization")
    organization = get_object_or_404(Organization.objects.select_related("onboarding_application"), pk=pk)
    if request.method == "POST":
        _require(request, "organizations.change_organization")
        action = request.POST.get("action")
        try:
            if action == "suspend":
                suspend_organization(organization=organization, actor=request.user, request=request)
                messages.success(request, _text(request, "Organization suspended and audited.", "تم إيقاف المنظمة وتسجيل العملية."))
            elif action == "reactivate":
                reactivate_organization(organization=organization, actor=request.user, request=request)
                messages.success(request, _text(request, "Organization reactivated and audited.", "تمت إعادة تفعيل المنظمة وتسجيل العملية."))
            else:
                raise ValidationError("Unsupported organization action.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        return HttpResponseRedirect(reverse("fabinzi_admin:maneg-organization-detail", args=[organization.pk]))
    members = organization.memberships.select_related("user").order_by("role", "joined_at") if request.user.has_perm("organizations.view_membership") else []
    documents = organization.onboarding_application.verification_documents.select_related("media_asset") if hasattr(organization, "onboarding_application") and request.user.has_perm("organizations.view_verificationdocument") else []
    return _render(request, "maneg/organization_detail.html", **_context(request, section="organizations", title_en="Organization", title_ar="المنظمة", organization=organization, members=members, documents=documents))


def verification(request):
    _require(request, "organizations.view_onboardingapplication")
    qs = OnboardingApplication.objects.select_related("organization", "reviewed_by").order_by("-updated_at")
    status = request.GET.get("status", "submitted")
    kind = request.GET.get("kind", "")
    if status in dict(OnboardingApplication.Status.choices): qs = qs.filter(status=status)
    if kind in dict(Organization.Kind.choices): qs = qs.filter(organization__kind=kind)
    return _render(request, "maneg/verification.html", **_context(request, section="verification", title_en="Verification & onboarding", title_ar="التحقق والانضمام", applications=qs[:100], status=status, kind=kind))


def verification_detail(request, pk):
    _require(request, "organizations.view_onboardingapplication")
    application = get_object_or_404(OnboardingApplication.objects.select_related("organization", "reviewed_by"), pk=pk)
    if request.method == "POST":
        _require(request, "organizations.change_onboardingapplication", "organizations.change_organization")
        decision = request.POST.get("decision", "")
        notes = request.POST.get("review_notes", "").strip()
        try:
            review_application(application=application, reviewer=request.user, decision=decision, notes=notes, request=request)
            messages.success(request, _text(request, "Verification decision recorded.", "تم تسجيل قرار التحقق."))
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        return HttpResponseRedirect(reverse("fabinzi_admin:maneg-verification-detail", args=[application.pk]))
    documents = application.verification_documents.select_related("media_asset") if request.user.has_perm("organizations.view_verificationdocument") else []
    members = application.organization.memberships.select_related("user") if request.user.has_perm("organizations.view_membership") else []
    return _render(request, "maneg/verification_detail.html", **_context(request, section="verification", title_en="Verification review", title_ar="مراجعة التحقق", application=application, documents=documents, members=members))


def design_review(request):
    _require(request, "design.view_garmentdesignversion")
    qs = GarmentDesignVersion.objects.select_related("design", "design__organization", "reviewed_by").order_by("-submitted_at", "-id")
    status = request.GET.get("status", "submitted")
    if status in dict(GarmentDesignVersion.Status.choices): qs = qs.filter(status=status)
    return _render(request, "maneg/design_review.html", **_context(request, section="designs", title_en="Garment Design review", title_ar="مراجعة تصميم القطع", versions=qs[:100], status=status))


def design_review_detail(request, pk):
    _require(request, "design.view_garmentdesignversion")
    version = get_object_or_404(GarmentDesignVersion.objects.select_related("design", "design__organization", "reviewed_by"), pk=pk)
    if request.method == "POST":
        _require(request, "design.change_garmentdesignversion", "design.add_technicalreview")
        try:
            review_version(version=version, reviewer=request.user, decision=request.POST.get("decision", ""), notes=request.POST.get("review_notes", "").strip(), request=request)
            messages.success(request, _text(request, "Technical review recorded.", "تم تسجيل المراجعة الفنية."))
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        return HttpResponseRedirect(reverse("fabinzi_admin:maneg-design-review-detail", args=[version.pk]))
    assets = version.assets.select_related("media_asset") if request.user.has_perm("design.view_designasset") else []
    return _render(request, "maneg/design_review_detail.html", **_context(request, section="designs", title_en="Technical design review", title_ar="المراجعة الفنية للتصميم", version=version, size_rows=version.size_rows.all(), zones=version.decoration_zones.all(), assets=assets, reviews=version.reviews.select_related("reviewer")[:20]))


def artwork_ip(request):
    _require(request, "artwork.view_artworkversion", "artwork.view_ipcase", any_of=True)
    versions = ArtworkVersion.objects.none()
    cases = IPCase.objects.none()
    products = DesignedProduct.objects.none()
    if request.user.has_perm("artwork.view_artworkversion"):
        versions = ArtworkVersion.objects.select_related("artwork", "artwork__organization", "reviewed_by").order_by("-submitted_at", "-id")[:60]
    if request.user.has_perm("artwork.view_ipcase"):
        cases = IPCase.objects.select_related("artwork", "designed_product", "assigned_to").order_by("-created_at")[:60]
    if request.user.has_perm("artwork.view_designedproduct"):
        products = DesignedProduct.objects.select_related("organization", "garment_version", "artwork_version").order_by("-updated_at")[:40]
    return _render(request, "maneg/artwork_ip.html", **_context(request, section="artwork", title_en="Artwork & IP moderation", title_ar="مراجعة الأعمال الفنية والحقوق", versions=versions, cases=cases, products=products))


def artwork_version_detail(request, pk):
    _require(request, "artwork.view_artworkversion")
    version = get_object_or_404(ArtworkVersion.objects.select_related("artwork", "artwork__organization", "reviewed_by"), pk=pk)
    if request.method == "POST":
        _require(request, "artwork.change_artworkversion", "artwork.add_artworkreview")
        try:
            review_artwork_version(version=version, reviewer=request.user, decision=request.POST.get("decision", ""), notes=request.POST.get("review_notes", "").strip(), request=request)
            messages.success(request, _text(request, "Artwork review recorded.", "تم تسجيل مراجعة العمل الفني."))
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        return HttpResponseRedirect(reverse("fabinzi_admin:maneg-artwork-version-detail", args=[version.pk]))
    assets = version.assets.select_related("media_asset") if request.user.has_perm("artwork.view_artworkasset") else []
    declaration = getattr(version, "ip_declaration", None) if request.user.has_perm("artwork.view_ipdeclaration") else None
    return _render(request, "maneg/artwork_version_detail.html", **_context(request, section="artwork", title_en="Artwork review", title_ar="مراجعة العمل الفني", version=version, assets=assets, declaration=declaration, reviews=version.reviews.select_related("reviewer")[:20]))


def ip_case_detail(request, pk):
    _require(request, "artwork.view_ipcase")
    case = get_object_or_404(IPCase.objects.select_related("artwork", "designed_product", "assigned_to"), pk=pk)
    if request.method == "POST":
        _require(request, "artwork.change_ipcase")
        action = request.POST.get("action")
        mapping = {
            "takedown": (IPCase.Status.RESOLVED, IPCase.Resolution.TAKEDOWN),
            "dismiss": (IPCase.Status.DISMISSED, IPCase.Resolution.CLAIM_REJECTED),
            "restore": (IPCase.Status.RESOLVED, IPCase.Resolution.RESTORED),
        }
        if action not in mapping:
            raise ValidationError("Unsupported IP moderation action.")
        status, resolution = mapping[action]
        moderate_ip_case(case=case, reviewer=request.user, status=status, resolution=resolution, notes=request.POST.get("staff_notes", "").strip(), request=request)
        messages.success(request, _text(request, "IP moderation action recorded.", "تم تسجيل إجراء حقوق الملكية."))
        return HttpResponseRedirect(reverse("fabinzi_admin:maneg-ip-case-detail", args=[case.pk]))
    evidence = case.evidence.select_related("media_asset", "submitted_by") if request.user.has_perm("artwork.view_ipcaseevidence") else []
    return _render(request, "maneg/ip_case_detail.html", **_context(request, section="artwork", title_en="IP case", title_ar="قضية حقوق ملكية", case=case, evidence=evidence, can_view_private_case=request.user.has_perm("artwork.change_ipcase")))


def catalog(request):
    _require(request, "storefront.view_storefront", "storefront.view_storeproduct", any_of=True)
    stores = Storefront.objects.none(); products = StoreProduct.objects.none()
    if request.user.has_perm("storefront.view_storefront"):
        stores = Storefront.objects.select_related("organization").order_by("name_en")[:80]
    if request.user.has_perm("storefront.view_storeproduct"):
        products = StoreProduct.objects.select_related("storefront", "storefront__organization", "designed_product").prefetch_related("variants").order_by("-updated_at")[:100]
    return _render(request, "maneg/catalog.html", **_context(request, section="catalog", title_en="Catalog & Store", title_ar="المتجر والكتالوج", stores=stores, products=products))


def orders(request):
    _require(request, "checkout.view_customerpurchase", "checkout.view_customerorder", any_of=True)
    purchases = CustomerPurchase.objects.none(); child_orders = CustomerOrder.objects.none(); attempts = PaymentAttempt.objects.none()
    if request.user.has_perm("checkout.view_customerpurchase"):
        purchases = CustomerPurchase.objects.select_related("customer").prefetch_related("child_orders").order_by("-created_at")[:80]
    if request.user.has_perm("checkout.view_customerorder"):
        child_orders = CustomerOrder.objects.select_related("purchase", "customer", "designer_organization").order_by("-created_at")[:100]
    if request.user.has_perm("checkout.view_paymentattempt"):
        attempts = PaymentAttempt.objects.select_related("purchase", "order").order_by("-created_at")[:50]
    return _render(request, "maneg/orders.html", **_context(request, section="orders", title_en="Purchases & operational orders", title_ar="المشتريات والطلبات التشغيلية", purchases=purchases, child_orders=child_orders, attempts=attempts))


def production(request):
    _require(request, "operations.view_productionjob", "operations.view_fulfillmentrecord", any_of=True)
    jobs = ProductionJob.objects.none(); fulfillment = FulfillmentRecord.objects.none()
    if request.user.has_perm("operations.view_productionjob"):
        jobs = ProductionJob.objects.select_related("order", "manufacturer").prefetch_related("milestones", "qc_inspections").order_by("-updated_at")[:100]
    if request.user.has_perm("operations.view_fulfillmentrecord"):
        fulfillment = FulfillmentRecord.objects.select_related("order").prefetch_related("events").order_by("-updated_at")[:100]
    return _render(request, "maneg/production.html", **_context(request, section="production", title_en="Production & fulfillment", title_ar="الإنتاج والتنفيذ", jobs=jobs, fulfillments=fulfillment))


def finance(request):
    _require(request, "finance.view_financeaccount", "finance.view_settlementrequest", any_of=True)
    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action in {"approve_settlement", "reject_settlement", "mark_paid"}:
                _require(request, "finance.change_settlementrequest")
                settlement = get_object_or_404(SettlementRequest, pk=request.POST.get("settlement_id"))
                if action == "mark_paid":
                    mark_settlement_paid(settlement=settlement, reviewer=request.user, external_reference=request.POST.get("external_reference", ""), request=request)
                else:
                    decision = SettlementRequest.Status.APPROVED if action == "approve_settlement" else SettlementRequest.Status.REJECTED
                    review_settlement(settlement=settlement, reviewer=request.user, decision=decision, notes=request.POST.get("review_notes", ""), request=request)
            elif action in {"verify_payout", "reject_payout"}:
                _require(request, "finance.change_payoutprofile")
                profile = get_object_or_404(PayoutProfile, pk=request.POST.get("profile_id"))
                decision = PayoutProfile.Status.VERIFIED if action == "verify_payout" else PayoutProfile.Status.REJECTED
                review_payout_profile(profile=profile, reviewer=request.user, decision=decision, notes=request.POST.get("review_notes", ""), request=request)
            else:
                raise ValidationError("Unsupported finance action.")
            messages.success(request, _text(request, "Finance action recorded and audited.", "تم تسجيل الإجراء المالي وتدقيقه."))
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
        return HttpResponseRedirect(reverse("fabinzi_admin:maneg-finance"))
    accounts = []
    if request.user.has_perm("finance.view_financeaccount"):
        for account in FinanceAccount.objects.select_related("organization").order_by("currency", "id")[:50]:
            account.maneg_balance = account_balance(account)
            accounts.append(account)
    settlements = SettlementRequest.objects.select_related("organization", "payout_profile", "reviewed_by", "paid_by").order_by("-requested_at")[:80] if request.user.has_perm("finance.view_settlementrequest") else []
    payouts = PayoutProfile.objects.select_related("organization", "verified_by").order_by("-updated_at")[:50] if request.user.has_perm("finance.view_payoutprofile") else []
    order_finances = OrderFinance.objects.select_related("order", "designer_account", "manufacturer_account").order_by("-recognized_at")[:50] if request.user.has_perm("finance.view_orderfinance") else []
    return _render(request, "maneg/finance.html", **_context(request, section="finance", title_en="Finance, payouts & settlements", title_ar="المالية والمدفوعات والتسويات", accounts=accounts, settlements=settlements, payouts=payouts, order_finances=order_finances))


def integrations(request):
    _require(request, "integrations.view_integrationconfig")
    configs = IntegrationConfig.objects.select_related("updated_by").order_by("provider")
    for config in configs:
        config.maneg_secret_configured = bool(config.encrypted_secrets)
    return _render(request, "maneg/integrations.html", **_context(request, section="integrations", title_en="Integrations", title_ar="التكاملات", integrations=configs))


def integration_detail(request, pk):
    _require(request, "integrations.view_integrationconfig")
    config = get_object_or_404(IntegrationConfig.objects.select_related("updated_by"), pk=pk)
    if request.method == "POST":
        _require(request, "integrations.change_integrationconfig")
        action = request.POST.get("action", "save")
        if action == "test":
            try:
                result = run_integration_test(config=config, actor=request.user, request=request)
                messages.success(request, result.message)
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
        else:
            form = IntegrationConfigAdminForm(request.POST, instance=config)
            if form.is_valid():
                save_integration_config(config=config, form=form, actor=request.user, request=request)
                messages.success(request, _text(request, "Integration configuration saved. Secret values remain write-only.", "تم حفظ إعداد التكامل. تظل القيم السرية للكتابة فقط."))
            else:
                return _render(request, "maneg/integration_detail.html", **_context(request, section="integrations", title_en="Integration configuration", title_ar="إعداد التكامل", integration=config, form=form, secret_configured=bool(config.encrypted_secrets)))
        return HttpResponseRedirect(reverse("fabinzi_admin:maneg-integration-detail", args=[config.pk]))
    form = IntegrationConfigAdminForm(instance=config)
    return _render(request, "maneg/integration_detail.html", **_context(request, section="integrations", title_en="Integration configuration", title_ar="إعداد التكامل", integration=config, form=form, secret_configured=bool(config.encrypted_secrets)))


def notifications(request):
    _require(request, "notifications.view_notificationdelivery")
    deliveries = NotificationDelivery.objects.select_related("notification", "notification__recipient").order_by("-updated_at")[:120]
    preferences = NotificationPreference.objects.select_related("user").order_by("-updated_at")[:80] if request.user.has_perm("notifications.view_notificationpreference") else []
    return _render(request, "maneg/notifications.html", **_context(request, section="notifications", title_en="Notification delivery", title_ar="تسليم الإشعارات", deliveries=deliveries, preferences=preferences))


def announcements(request):
    _require(request, "platform_ops.view_platformannouncement")
    edit_id = request.GET.get("edit") or request.POST.get("announcement_id")
    instance = get_object_or_404(PlatformAnnouncement, pk=edit_id) if edit_id else None
    if request.method == "POST":
        _require(request, "platform_ops.change_platformannouncement" if instance else "platform_ops.add_platformannouncement")
        form = PlatformAnnouncementForm(request.POST, instance=instance, language=_lang(request))
        if form.is_valid():
            save_announcement(form=form, actor=request.user, request=request)
            messages.success(request, _text(request, "Announcement saved and audited.", "تم حفظ الإعلان وتسجيله في سجل التدقيق."))
            return HttpResponseRedirect(reverse("fabinzi_admin:maneg-announcements"))
    else:
        form = PlatformAnnouncementForm(instance=instance, language=_lang(request), initial={"starts_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M")})
    rows = PlatformAnnouncement.objects.select_related("created_by").order_by("-updated_at")[:80]
    return _render(request, "maneg/announcements.html", **_context(request, section="announcements", title_en="Announcement Banner", title_ar="شريط الإعلان", announcements=rows, form=form, editing=instance))


def maintenance(request):
    _require(request, "platform_ops.view_maintenancewindow")
    edit_id = request.GET.get("edit") or request.POST.get("maintenance_id")
    instance = get_object_or_404(MaintenanceWindow, pk=edit_id) if edit_id else None
    if request.method == "POST":
        _require(request, "platform_ops.change_maintenancewindow" if instance else "platform_ops.add_maintenancewindow")
        form = MaintenanceWindowForm(request.POST, instance=instance, language=_lang(request))
        if form.is_valid():
            save_maintenance(form=form, actor=request.user, request=request)
            messages.success(request, _text(request, "Maintenance state saved and audited. Control Center bypass remains enabled.", "تم حفظ وضع الصيانة وتسجيله. يظل تجاوز مركز التحكم مفعلاً لمنع الإغلاق الإداري."))
            return HttpResponseRedirect(reverse("fabinzi_admin:maneg-maintenance"))
    else:
        form = MaintenanceWindowForm(instance=instance, language=_lang(request), initial={"starts_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M")})
    rows = MaintenanceWindow.objects.select_related("created_by").order_by("-updated_at")[:80]
    return _render(request, "maneg/maintenance.html", **_context(request, section="maintenance", title_en="Maintenance Mode", title_ar="وضع الصيانة", windows=rows, current=MaintenanceWindow.current(), form=form, editing=instance))


def audit_log(request):
    _require(request, "audit.view_auditevent")
    qs = AuditEvent.objects.select_related("actor").order_by("-created_at")
    query = _q(request)
    action = request.GET.get("action", "").strip()[:80]
    actor = request.GET.get("actor", "").strip()[:80]
    if query:
        qs = qs.filter(Q(action__icontains=query) | Q(object_type__icontains=query) | Q(object_id__icontains=query))
    if action: qs = qs.filter(action__icontains=action)
    if actor: qs = qs.filter(Q(actor__username__icontains=actor) | Q(actor__email__icontains=actor))
    return _render(request, "maneg/audit.html", **_context(request, section="audit", title_en="Audit Log", title_ar="سجل التدقيق", events=qs[:150], query=query, action_filter=action, actor_filter=actor))


def system_status(request):
    if not request.user.is_superuser:
        raise PermissionDenied("System/security status is restricted to superusers.")
    database_ok = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            database_ok = cursor.fetchone() == (1,)
    except Exception:
        database_ok = False
    redis_ok = False
    try:
        from redis import Redis
        redis_ok = bool(Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1).ping())
    except Exception:
        redis_ok = False
    security = {
        "environment": settings.ENVIRONMENT,
        "debug": settings.DEBUG,
        "secure_session_cookie": settings.SESSION_COOKIE_SECURE,
        "secure_csrf_cookie": settings.CSRF_COOKIE_SECURE,
        "ssl_redirect": settings.SECURE_SSL_REDIRECT,
        "hsts_seconds": settings.SECURE_HSTS_SECONDS,
        "private_media_mode": settings.PRIVATE_MEDIA_STORAGE_MODE,
        "sentry_configured": bool(settings.SENTRY_ENABLED and settings.SENTRY_DSN),
        "celery_broker_configured": bool(settings.CELERY_BROKER_URL),
        "database_ok": database_ok,
        "redis_ok": redis_ok,
        "maintenance_active": bool(MaintenanceWindow.current()),
    }
    return _render(request, "maneg/system.html", **_context(request, section="system", title_en="Security / System Status", title_ar="حالة الأمان والنظام", security=security))


def private_evidence(request, asset_type, pk):
    asset = None
    if asset_type == "verification":
        _require(request, "organizations.view_verificationdocument", "media.view_mediaasset")
        record = get_object_or_404(VerificationDocument.objects.select_related("media_asset"), pk=pk)
        asset = record.media_asset
    elif asset_type == "design":
        _require(request, "design.view_designasset", "media.view_mediaasset")
        record = get_object_or_404(DesignAsset.objects.select_related("media_asset"), pk=pk)
        asset = record.media_asset
    elif asset_type in {"artwork-source", "artwork-rights"}:
        required = ["artwork.view_artworkasset", "media.view_mediaasset"]
        kind = ArtworkAsset.Kind.SOURCE if asset_type == "artwork-source" else ArtworkAsset.Kind.RIGHTS_EVIDENCE
        if asset_type == "artwork-rights":
            required.append("artwork.view_ipdeclaration")
        _require(request, *required)
        record = get_object_or_404(ArtworkAsset.objects.select_related("media_asset"), pk=pk, kind=kind)
        asset = record.media_asset
    elif asset_type == "ip-evidence":
        _require(request, "artwork.view_ipcase", "artwork.view_ipcaseevidence", "media.view_mediaasset")
        record = get_object_or_404(IPCaseEvidence.objects.select_related("media_asset"), pk=pk)
        asset = record.media_asset
    else:
        raise Http404
    try:
        payload = private_media_response(asset)
    except Exception as exc:
        raise Http404 from exc
    if isinstance(payload, str):
        response = HttpResponseRedirect(payload)
    else:
        response = FileResponse(payload, content_type=asset.mime_type)
        safe_name = asset.original_filename.replace(chr(34), "")
        response["Content-Disposition"] = f'inline; filename="{safe_name}"'
        response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["Referrer-Policy"] = "no-referrer"
    return response


def expert_admin(request):
    from apps.integrations.admin_site import fabinzi_admin_site
    apps = fabinzi_admin_site.get_app_list(request)
    return _render(request, "maneg/expert.html", **_context(request, section="expert", title_en="Django Admin registry", title_ar="إدارة Django المتقدمة", admin_apps=apps))
