from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core.exceptions import PermissionDenied, ValidationError

from apps.checkout.models import CustomerOrder
from apps.manufacturer_marketplace.models import ManufacturerSelection
from apps.organizations.models import Membership
from .models import FulfillmentRecord, ProductionJob, ProductionMilestone
from .services import assign_manufacturer, can_view_operations, deliver_order, pack_order, record_qc, request_qc, ship_order, start_production, update_milestone


def _error(exc): return Response({"detail":str(exc)},status=403 if isinstance(exc,PermissionDenied) else 400)

def _job(job): return {"id":job.id,"order_id":job.order_id,"manufacturer_id":job.manufacturer_id,"selection_id":job.selection_id,"status":job.status,"target_completion_date":job.target_completion_date,"milestones":[{"id":m.id,"kind":m.kind,"status":m.status,"notes":m.notes} for m in job.milestones.all()],"qc":[{"id":q.id,"decision":q.decision,"notes":q.notes,"created_at":q.created_at} for q in job.qc_inspections.all()]}

def _fulfill(f): return {"id":f.id,"order_id":f.order_id,"status":f.status,"carrier":f.carrier,"tracking_number":f.tracking_number,"tracking_url":f.tracking_url,"events":[{"status":e.status,"note":e.note,"created_at":e.created_at} for e in f.events.all()]}


class OrderOperationsAPIView(APIView):
    def get(self,request,order_id):
        order=get_object_or_404(CustomerOrder.objects.select_related("designer_organization"),pk=order_id)
        if not can_view_operations(request.user,order): return Response({"detail":"Forbidden"},status=403)
        job=ProductionJob.objects.filter(order=order).prefetch_related("milestones","qc_inspections").first(); f=FulfillmentRecord.objects.filter(order=order).prefetch_related("events").first()
        return Response({"production":_job(job) if job else None,"fulfillment":_fulfill(f) if f else None})


class ProductionJobsAPIView(APIView):
    def get(self,request):
        memberships=Membership.objects.filter(user=request.user,is_active=True)
        org_ids=list(memberships.values_list("organization_id",flat=True)); qs=ProductionJob.objects.filter(models_q(org_ids)).select_related("order","manufacturer").prefetch_related("milestones","qc_inspections").distinct()
        return Response([_job(j) for j in qs])


def models_q(org_ids):
    from django.db.models import Q
    return Q(manufacturer_id__in=org_ids)|Q(order__designer_organization_id__in=org_ids)


class AssignManufacturerAPIView(APIView):
    def post(self,request,job_id):
        try:
            job=get_object_or_404(ProductionJob,pk=job_id); selection=get_object_or_404(ManufacturerSelection,pk=request.data.get("selection_id")); return Response(_job(assign_manufacturer(job=job,selection=selection,actor=request.user,request=request)))
        except (PermissionDenied,ValidationError) as exc: return _error(exc)


class StartProductionAPIView(APIView):
    def post(self,request,job_id):
        try: return Response(_job(start_production(job=get_object_or_404(ProductionJob,pk=job_id),actor=request.user,request=request)))
        except (PermissionDenied,ValidationError) as exc: return _error(exc)


class MilestoneUpdateAPIView(APIView):
    def post(self,request,milestone_id):
        try:
            m=update_milestone(milestone=get_object_or_404(ProductionMilestone,pk=milestone_id),actor=request.user,status=request.data.get("status",""),notes=request.data.get("notes",""),request=request); return Response({"id":m.id,"kind":m.kind,"status":m.status,"notes":m.notes})
        except (PermissionDenied,ValidationError) as exc: return _error(exc)


class RequestQCAPIView(APIView):
    def post(self,request,job_id):
        try: return Response(_job(request_qc(job=get_object_or_404(ProductionJob,pk=job_id),actor=request.user,request=request)))
        except (PermissionDenied,ValidationError) as exc: return _error(exc)


class RecordQCAPIView(APIView):
    def post(self,request,job_id):
        try:
            q=record_qc(job=get_object_or_404(ProductionJob,pk=job_id),actor=request.user,decision=request.data.get("decision",""),checklist=request.data.get("checklist",{}),notes=request.data.get("notes",""),request=request); return Response({"id":q.id,"decision":q.decision,"notes":q.notes})
        except (PermissionDenied,ValidationError) as exc: return _error(exc)


class PackAPIView(APIView):
    def post(self,request,fulfillment_id):
        try: return Response(_fulfill(pack_order(fulfillment=get_object_or_404(FulfillmentRecord,pk=fulfillment_id),actor=request.user,request=request)))
        except (PermissionDenied,ValidationError) as exc: return _error(exc)


class ShipAPIView(APIView):
    def post(self,request,fulfillment_id):
        try: return Response(_fulfill(ship_order(fulfillment=get_object_or_404(FulfillmentRecord,pk=fulfillment_id),actor=request.user,carrier=request.data.get("carrier",""),tracking_number=request.data.get("tracking_number",""),tracking_url=request.data.get("tracking_url",""),request=request)))
        except (PermissionDenied,ValidationError) as exc: return _error(exc)


class DeliverAPIView(APIView):
    def post(self,request,fulfillment_id):
        try: return Response(_fulfill(deliver_order(fulfillment=get_object_or_404(FulfillmentRecord,pk=fulfillment_id),actor=request.user,request=request)))
        except (PermissionDenied,ValidationError) as exc: return _error(exc)
