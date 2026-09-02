from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse

from apps.checkout.models import OrderItem
from apps.manufacturer_marketplace.models import ManufacturerQuote, RFQ
from apps.platform_ops.maneg_views import _context, _render
from .models import ProductionJob, ProductionSpecification
from .v2_7 import assign_customer_order_manufacturer, create_customer_order_routing, release_customer_order_production


def _require(request, permission):
    if not request.user.has_perm(permission):
        raise PermissionDenied("Your staff account does not have permission for this V2-7 production operation.")


def routing_console(request):
    _require(request, "operations.view_productionjob")
    if request.method == "POST":
        _require(request, "operations.change_productionjob")
        action = request.POST.get("action", "")
        try:
            if action == "route":
                item = get_object_or_404(OrderItem.objects.select_related("order"), pk=request.POST.get("order_item_id"))
                create_customer_order_routing(order_item=item, actor=request.user, request=request)
                messages.success(request, "CustomerOrder manufacturing routing created using operational eligibility only.")
            elif action == "assign":
                quote = get_object_or_404(ManufacturerQuote, pk=request.POST.get("quote_id"))
                assign_customer_order_manufacturer(quote=quote, actor=request.user, request=request)
                messages.success(request, "Manufacturer assigned and immutable ProductionSpecification created.")
            elif action == "release":
                job = get_object_or_404(ProductionJob, pk=request.POST.get("job_id"))
                release_customer_order_production(job=job, actor=request.user, request=request)
                messages.success(request, "Production released after canonical production-eligibility verification.")
            else:
                raise ValidationError("Unsupported V2-7 operation.")
        except (ValidationError, PermissionDenied) as exc:
            text = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            messages.error(request, text)
        return HttpResponseRedirect(reverse("fabinzi_admin:maneg-v2-7-routing"))

    rfqs = (
        RFQ.objects.filter(source=RFQ.Source.CUSTOMER_ORDER)
        .select_related("order_item__order", "order_item__store_product", "order_item__variant")
        .prefetch_related("invitations__manufacturer", "invitations__quote")
        .order_by("-updated_at")[:100]
    )
    jobs = (
        ProductionJob.objects.select_related("order__item", "manufacturer")
        .filter(order__item__manufacturing_rfq__source=RFQ.Source.CUSTOMER_ORDER)
        .order_by("-updated_at")[:100]
    )
    specifications = ProductionSpecification.objects.select_related("job__order", "manufacturer", "accepted_quote")[:100]
    context = _context(
        request,
        section="production",
        title_en="V2-7 Production Routing",
        title_ar="توجيه الإنتاج V2-7",
        rfqs=rfqs,
        jobs=jobs,
        specifications=specifications,
    )
    return _render(request, "maneg/v2_7_routing.html", **context)
