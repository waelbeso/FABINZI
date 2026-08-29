from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render

from apps.checkout.models import CustomerOrder
from apps.organizations.models import Membership
from .models import FulfillmentRecord, ProductionJob
from .services import can_view_operations


@login_required
def order_operations(request,pk):
    order=get_object_or_404(CustomerOrder.objects.select_related("designer_organization"),pk=pk)
    if not can_view_operations(request.user,order): raise PermissionDenied
    return render(request,"operations/order_operations.html",{"order":order,"job":ProductionJob.objects.filter(order=order).prefetch_related("milestones","qc_inspections").first(),"fulfillment":FulfillmentRecord.objects.filter(order=order).prefetch_related("events").first()})


@login_required
def manufacturer_production(request):
    org_ids=Membership.objects.filter(user=request.user,is_active=True,organization__kind="manufacturer").values_list("organization_id",flat=True)
    jobs=ProductionJob.objects.filter(manufacturer_id__in=org_ids).select_related("order","manufacturer").prefetch_related("milestones")
    return render(request,"operations/manufacturer_production.html",{"jobs":jobs})


@login_required
def designer_fulfillment(request):
    org_ids=Membership.objects.filter(user=request.user,is_active=True,organization__kind="designer").values_list("organization_id",flat=True)
    records=FulfillmentRecord.objects.filter(order__designer_organization_id__in=org_ids).select_related("order")
    return render(request,"operations/designer_fulfillment.html",{"records":records})
