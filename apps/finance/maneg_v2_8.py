from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse

from apps.media.services import private_media_response
from apps.platform_ops.maneg_views import _context, _render
from .models import FinancePolicy, FinanceRecognitionPending, PayoutProfile, SettlementRequest
from .services import activate_policy, preview_policy, reconcile_finance_pending, retire_policy, review_payout_profile, review_settlement, mark_settlement_processing, mark_settlement_paid, validate_policy_draft


class FinancePolicyForm(forms.ModelForm):
    class Meta:
        model = FinancePolicy
        fields = ["name", "currency", "fabinzi_rule_type", "fabinzi_rule_value", "garment_royalty_rule_type", "garment_royalty_rule_value", "artwork_royalty_rule_type", "artwork_royalty_rule_value", "manufacturer_include_unit_price", "manufacturer_include_setup_fee", "manufacturer_include_sample_fee", "manufacturer_include_shipping_estimate", "settlement_trigger", "settlement_hold_days", "v2_minimum_payout"]


def _require(request, permission):
    if not request.user.is_staff or not request.user.has_perm(permission): raise PermissionDenied("Your staff account does not have permission for this V2 finance operation.")


def finance_policy_list(request):
    _require(request, "finance.view_finance_policy_governance")
    policies = FinancePolicy.objects.exclude(code__startswith="LEGACY-").select_related("created_by", "activated_by", "retired_by")
    return _render(request, "maneg/v2_8_finance_policies.html", **_context(request, section="finance", title_en="V2 Finance Policy", title_ar="سياسة المالية V2", policies=policies))


def finance_policy_create(request):
    _require(request, "finance.manage_finance_policy_governance")
    if request.method == "POST":
        form = FinancePolicyForm(request.POST)
        if form.is_valid():
            import uuid
            policy = form.save(commit=False); policy.code = f"FIN-POL-{uuid.uuid4().hex[:10].upper()}"; policy.lifecycle_status = FinancePolicy.LifecycleStatus.DRAFT; policy.created_by = request.user; policy.is_active = False; policy.save()
            from apps.audit.services import record_audit_event
            record_audit_event(actor=request.user, action="finance.policy.draft_created", instance=policy, metadata={"code": policy.code}, request=request)
            messages.success(request, "Finance Policy draft created. It is not active.")
            return HttpResponseRedirect(reverse("fabinzi_admin:maneg-v2-8-finance-policy-detail", args=[policy.pk]))
    else: form = FinancePolicyForm()
    return _render(request, "maneg/v2_8_finance_policy_form.html", **_context(request, section="finance", title_en="New Finance Policy draft", title_ar="مسودة سياسة مالية جديدة", form=form, policy=None))


def finance_policy_detail(request, pk):
    _require(request, "finance.view_finance_policy_governance"); policy = get_object_or_404(FinancePolicy, pk=pk); editable = policy.lifecycle_status == FinancePolicy.LifecycleStatus.DRAFT and request.user.has_perm("finance.manage_finance_policy_governance"); form = FinancePolicyForm(instance=policy)
    if request.method == "POST":
        _require(request, "finance.manage_finance_policy_governance")
        if policy.lifecycle_status != FinancePolicy.LifecycleStatus.DRAFT: raise PermissionDenied("Historical Finance Policy versions are immutable.")
        action = request.POST.get("action", "save"); form = FinancePolicyForm(request.POST, instance=policy)
        if form.is_valid():
            policy = form.save(commit=False); policy.validated_at = None; policy.full_clean(); policy.save()
            from apps.audit.services import record_audit_event
            record_audit_event(actor=request.user, action="finance.policy.draft_updated", instance=policy, metadata={"code": policy.code}, request=request)
            if action == "validate":
                try: validate_policy_draft(policy=policy, actor=request.user, request=request)
                except ValidationError as exc: messages.error(request, "; ".join(exc.messages))
                else: messages.success(request, "Finance Policy draft validated. Activation remains a separate explicit action.")
            else: messages.success(request, "Finance Policy draft saved. Validation/activation status was not inferred.")
            return HttpResponseRedirect(reverse("fabinzi_admin:maneg-v2-8-finance-policy-detail", args=[policy.pk]))
    return _render(request, "maneg/v2_8_finance_policy_form.html", **_context(request, section="finance", title_en=f"Finance Policy {policy.code}", title_ar=f"سياسة المالية {policy.code}", form=form, policy=policy, editable=editable))


def finance_policy_activate(request, pk):
    _require(request, "finance.activate_finance_policy_governance"); policy = get_object_or_404(FinancePolicy, pk=pk)
    if request.method == "POST":
        try: activate_policy(policy=policy, actor=request.user, confirmed=request.POST.get("confirm") == "yes", request=request)
        except ValidationError as exc: messages.error(request, "; ".join(exc.messages))
        else: messages.success(request, f"{policy.code} activated. No blocked finance was reconciled automatically.")
        return HttpResponseRedirect(reverse("fabinzi_admin:maneg-v2-8-finance-policy-detail", args=[policy.pk]))
    return _render(request, "maneg/v2_8_finance_policy_confirm.html", **_context(request, section="finance", title_en="Confirm Finance Policy activation", title_ar="تأكيد تفعيل سياسة المالية", policy=policy, action="activate"))


def finance_policy_retire(request, pk):
    _require(request, "finance.activate_finance_policy_governance"); policy = get_object_or_404(FinancePolicy, pk=pk)
    if request.method == "POST":
        try: retire_policy(policy=policy, actor=request.user, confirmed=request.POST.get("confirm") == "yes", request=request)
        except ValidationError as exc: messages.error(request, "; ".join(exc.messages))
        else: messages.success(request, f"{policy.code} retired. Historical finance remains bound to it.")
        return HttpResponseRedirect(reverse("fabinzi_admin:maneg-v2-8-finance-policy-detail", args=[policy.pk]))
    return _render(request, "maneg/v2_8_finance_policy_confirm.html", **_context(request, section="finance", title_en="Confirm Finance Policy retirement", title_ar="تأكيد تقاعد سياسة المالية", policy=policy, action="retire"))


def finance_policy_preview(request, pk):
    _require(request, "finance.view_finance_policy_governance"); policy = get_object_or_404(FinancePolicy, pk=pk); result = None; error = ""
    try: result = preview_policy(policy)
    except ValidationError as exc: error = "; ".join(exc.messages)
    return _render(request, "maneg/v2_8_finance_preview.html", **_context(request, section="finance", title_en="Synthetic Finance Policy preview", title_ar="محاكاة سياسة المالية", policy=policy, preview=result, preview_error=error))


def finance_pending(request):
    _require(request, "finance.reconcile_finance_recognition"); pending = FinanceRecognitionPending.objects.select_related("order", "purchase", "order_item", "manufacturer_quote", "production_specification", "reconciled_finance").order_by("status", "created_at")[:200]
    return _render(request, "maneg/v2_8_finance_pending.html", **_context(request, section="finance", title_en="Pending finance reconciliation", title_ar="مطابقة المالية المعلقة", pending_records=pending))


def finance_pending_reconcile(request, pk):
    _require(request, "finance.reconcile_finance_recognition")
    if request.method != "POST": raise PermissionDenied("Finance reconciliation requires an explicit POST action.")
    pending = get_object_or_404(FinanceRecognitionPending, pk=pk)
    try: finance = reconcile_finance_pending(pending=pending, actor=request.user, request=request)
    except ValidationError as exc: messages.error(request, "; ".join(exc.messages))
    else: messages.success(request, f"Finance reconciled exactly once as OrderFinance #{finance.pk}, bound to {finance.finance_policy.code}.")
    return HttpResponseRedirect(reverse("fabinzi_admin:maneg-v2-8-finance-pending"))


def finance_payouts(request):
    _require(request, "finance.view_settlementrequest")
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action in {"verify_profile", "reject_profile"}:
                _require(request, "finance.change_payoutprofile"); profile = get_object_or_404(PayoutProfile, pk=request.POST.get("profile_id")); decision = PayoutProfile.Status.VERIFIED if action == "verify_profile" else PayoutProfile.Status.REJECTED; review_payout_profile(profile=profile, reviewer=request.user, decision=decision, notes=request.POST.get("notes", ""), request=request)
            else:
                settlement = get_object_or_404(SettlementRequest, pk=request.POST.get("settlement_id"))
                if action == "under_review": review_settlement(settlement=settlement, reviewer=request.user, decision=SettlementRequest.Status.UNDER_REVIEW, notes=request.POST.get("notes", ""), request=request)
                elif action == "approve": review_settlement(settlement=settlement, reviewer=request.user, decision=SettlementRequest.Status.APPROVED, notes=request.POST.get("notes", ""), request=request)
                elif action == "reject": review_settlement(settlement=settlement, reviewer=request.user, decision=SettlementRequest.Status.REJECTED, notes=request.POST.get("notes", ""), request=request)
                elif action == "processing": mark_settlement_processing(settlement=settlement, reviewer=request.user, execution_evidence=request.POST.get("execution_evidence", ""), request=request)
                elif action == "paid": mark_settlement_paid(settlement=settlement, reviewer=request.user, external_reference=request.POST.get("external_reference", ""), request=request)
                else: raise ValidationError("Unsupported payout action.")
        except (ValidationError, PermissionDenied) as exc: messages.error(request, str(exc))
        return HttpResponseRedirect(reverse("fabinzi_admin:maneg-v2-8-finance-payouts"))
    profiles = PayoutProfile.objects.select_related("organization", "verified_by", "bank_proof").order_by("-updated_at")[:100]; settlements = SettlementRequest.objects.select_related("organization", "payout_profile", "account").order_by("-requested_at")[:150]
    return _render(request, "maneg/v2_8_finance_payouts.html", **_context(request, section="finance", title_en="V2 Payout operations", title_ar="عمليات المدفوعات V2", profiles=profiles, settlements=settlements))


def payout_bank_proof(request, pk):
    _require(request, "finance.view_payoutprofile"); profile = get_object_or_404(PayoutProfile.objects.select_related("bank_proof"), pk=pk)
    if not profile.bank_proof_id: raise Http404
    try: payload = private_media_response(profile.bank_proof)
    except Exception as exc: raise Http404 from exc
    if isinstance(payload, str): return HttpResponseRedirect(payload)
    response = FileResponse(payload, content_type=profile.bank_proof.mime_type); response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow, noarchive"; return response
