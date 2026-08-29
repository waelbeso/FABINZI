from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit_event
from apps.checkout.models import CustomerOrder
from apps.notifications.models import Notification
from apps.organizations.models import Membership, Organization
from apps.storefront.models import StoreProduct
from .models import FulfillmentEvent, FulfillmentRecord, ProductionAsset, ProductionJob, ProductionMilestone, QCInspection

DESIGNER_OP_ROLES={Membership.Role.OWNER,Membership.Role.MANAGER}
MFR_PRODUCTION_ROLES={Membership.Role.OWNER,Membership.Role.MANAGER,Membership.Role.PRODUCTION_MANAGER,Membership.Role.OPERATOR}
MFR_QC_ROLES={Membership.Role.OWNER,Membership.Role.MANAGER,Membership.Role.PRODUCTION_MANAGER,Membership.Role.QC}


def _membership(actor, organization, roles):
    if getattr(actor,"is_staff",False): return None
    if not getattr(actor,"is_authenticated",False): raise PermissionDenied("Authentication required.")
    membership=Membership.objects.filter(organization=organization,user=actor,is_active=True).first()
    if not membership or membership.role not in roles: raise PermissionDenied("Business role does not permit this operation.")
    return membership


def require_designer_operations(actor, order):
    _membership(actor,order.designer_organization,DESIGNER_OP_ROLES)


def require_manufacturer_job_access(actor, job, roles=MFR_PRODUCTION_ROLES):
    if not job.manufacturer_id: raise PermissionDenied("No Manufacturer is assigned.")
    _membership(actor,job.manufacturer,roles)


def can_view_operations(actor, order):
    if getattr(actor,"is_staff",False): return True
    if not getattr(actor,"is_authenticated",False): return False
    if order.customer_id == actor.pk: return True
    return Membership.objects.filter(user=actor,is_active=True,organization_id__in=[order.designer_organization_id,getattr(getattr(order,"production_job",None),"manufacturer_id",None)]).exists()


def _event(fulfillment,status,actor=None,note=""):
    return FulfillmentEvent.objects.create(fulfillment=fulfillment,status=status,actor=actor,note=note)


def _notify_customer(order,title_en,title_ar,body_en,body_ar):
    Notification.objects.create(recipient=order.customer,type="order_status",title_en=title_en,title_ar=title_ar,body_en=body_en,body_ar=body_ar,destination=f"/orders/{order.pk}/production/")


@transaction.atomic
def start_order_operations(*, order, actor=None, request=None):
    order=CustomerOrder.objects.select_related("item__store_product").get(pk=order.pk)
    if order.status != CustomerOrder.Status.CONFIRMED: raise ValidationError("Only confirmed orders can enter operations.")
    stock=order.item.store_product.fulfillment_mode == StoreProduct.FulfillmentMode.STOCK
    fulfillment,created=FulfillmentRecord.objects.get_or_create(order=order,defaults={"status":FulfillmentRecord.Status.READY_TO_PACK if stock else FulfillmentRecord.Status.WAITING_PRODUCTION})
    if created: _event(fulfillment,fulfillment.status,actor,"Operations initialized")
    job=None
    if not stock:
        job,job_created=ProductionJob.objects.get_or_create(order=order)
        if job_created:
            for kind,_ in ProductionMilestone.Kind.choices: ProductionMilestone.objects.create(job=job,kind=kind)
            record_audit_event(actor=actor,action="production_job.created",instance=job,metadata={"order_id":order.pk},request=request)
    return job,fulfillment


@transaction.atomic
def assign_manufacturer(*, job, selection, actor, request=None):
    job=ProductionJob.objects.select_for_update().get(pk=job.pk)
    require_designer_operations(actor,job.order)
    if job.status != ProductionJob.Status.AWAITING_ASSIGNMENT: raise ValidationError("Manufacturer can only be assigned before production is queued.")
    if selection.rfq.designed_product_id != job.order.item.store_product.designed_product_id: raise ValidationError("Selection does not match this order's Designed Product.")
    if selection.quote.status != "accepted": raise ValidationError("Manufacturer selection must reference an accepted quote.")
    if selection.manufacturer.verification_status != Organization.VerificationStatus.ACTIVE: raise ValidationError("Manufacturer must be active.")
    job.selection=selection; job.manufacturer=selection.manufacturer; job.status=ProductionJob.Status.QUEUED; job.assigned_at=timezone.now(); job.full_clean(); job.save()
    record_audit_event(actor=actor,action="production_job.manufacturer_assigned",instance=job,metadata={"manufacturer_id":job.manufacturer_id,"selection_id":selection.pk},request=request)
    return job


@transaction.atomic
def start_production(*, job, actor, request=None):
    job=ProductionJob.objects.select_for_update().get(pk=job.pk); require_manufacturer_job_access(actor,job)
    if job.status not in {ProductionJob.Status.QUEUED,ProductionJob.Status.QC_FAILED}: raise ValidationError("Production cannot start from its current state.")
    job.status=ProductionJob.Status.IN_PRODUCTION; job.started_at=job.started_at or timezone.now(); job.save(update_fields=["status","started_at","updated_at"])
    record_audit_event(actor=actor,action="production_job.started",instance=job,request=request); return job


@transaction.atomic
def update_milestone(*, milestone, actor, status, notes="", request=None):
    milestone=ProductionMilestone.objects.select_for_update().get(pk=milestone.pk); job=milestone.job; require_manufacturer_job_access(actor,job)
    if job.status != ProductionJob.Status.IN_PRODUCTION: raise ValidationError("Milestones can only change while production is active.")
    if status not in dict(ProductionMilestone.Status.choices): raise ValidationError("Invalid milestone status.")
    milestone.status=status; milestone.notes=notes; milestone.updated_by=actor
    if status==ProductionMilestone.Status.IN_PROGRESS and not milestone.started_at: milestone.started_at=timezone.now()
    if status==ProductionMilestone.Status.COMPLETED: milestone.started_at=milestone.started_at or timezone.now(); milestone.completed_at=timezone.now()
    elif status!=ProductionMilestone.Status.COMPLETED: milestone.completed_at=None
    milestone.save(); record_audit_event(actor=actor,action="production_milestone.updated",instance=milestone,metadata={"status":status},request=request); return milestone


@transaction.atomic
def request_qc(*, job, actor, request=None):
    job=ProductionJob.objects.select_for_update().get(pk=job.pk); require_manufacturer_job_access(actor,job)
    if job.status != ProductionJob.Status.IN_PRODUCTION: raise ValidationError("Production must be active before QC.")
    if job.milestones.exclude(status=ProductionMilestone.Status.COMPLETED).exists(): raise ValidationError("All production milestones must be completed before QC.")
    job.status=ProductionJob.Status.QC_PENDING; job.save(update_fields=["status","updated_at"]); record_audit_event(actor=actor,action="production_job.qc_requested",instance=job,request=request); return job


@transaction.atomic
def record_qc(*, job, actor, decision, checklist=None, notes="", request=None):
    job=ProductionJob.objects.select_for_update().get(pk=job.pk); require_manufacturer_job_access(actor,job,MFR_QC_ROLES)
    if job.status != ProductionJob.Status.QC_PENDING: raise ValidationError("QC inspection requires a QC-pending job.")
    if decision not in dict(QCInspection.Decision.choices): raise ValidationError("Invalid QC decision.")
    inspection=QCInspection.objects.create(job=job,decision=decision,checklist=checklist or {},notes=notes,inspected_by=actor)
    if decision==QCInspection.Decision.PASSED:
        job.status=ProductionJob.Status.READY; job.ready_at=timezone.now(); job.save(update_fields=["status","ready_at","updated_at"])
        f=job.order.fulfillment; f.status=FulfillmentRecord.Status.READY_TO_PACK; f.save(update_fields=["status","updated_at"]); _event(f,f.status,actor,"QC passed")
    else:
        job.status=ProductionJob.Status.QC_FAILED; job.save(update_fields=["status","updated_at"])
    record_audit_event(actor=actor,action="production_job.qc_recorded",instance=job,metadata={"decision":decision},request=request); return inspection


@transaction.atomic
def add_production_asset(*, job, actor, media_asset, kind, label="", request=None):
    require_manufacturer_job_access(actor,job)
    if media_asset.uploaded_by_id not in {None,actor.pk} and not actor.is_staff: raise PermissionDenied("Media ownership mismatch.")
    asset=ProductionAsset(job=job,media_asset=media_asset,kind=kind,label=label,uploaded_by=actor); asset.full_clean(); asset.save(); record_audit_event(actor=actor,action="production_asset.added",instance=asset,request=request); return asset


def _require_fulfillment_actor(actor, fulfillment):
    order=fulfillment.order
    if getattr(actor,"is_staff",False): return
    if Membership.objects.filter(user=actor,is_active=True,organization=order.designer_organization,role__in=DESIGNER_OP_ROLES).exists(): return
    job=getattr(order,"production_job",None)
    if job and job.manufacturer_id and Membership.objects.filter(user=actor,is_active=True,organization_id=job.manufacturer_id,role__in=MFR_PRODUCTION_ROLES).exists(): return
    raise PermissionDenied("Fulfillment access denied.")


@transaction.atomic
def pack_order(*, fulfillment, actor, request=None):
    fulfillment=FulfillmentRecord.objects.select_for_update().select_related("order").get(pk=fulfillment.pk); _require_fulfillment_actor(actor,fulfillment)
    if fulfillment.status != FulfillmentRecord.Status.READY_TO_PACK: raise ValidationError("Order is not ready to pack.")
    fulfillment.status=FulfillmentRecord.Status.PACKED; fulfillment.packed_at=timezone.now(); fulfillment.save(update_fields=["status","packed_at","updated_at"]); _event(fulfillment,fulfillment.status,actor)
    record_audit_event(actor=actor,action="fulfillment.packed",instance=fulfillment,request=request); return fulfillment


@transaction.atomic
def ship_order(*, fulfillment, actor, carrier, tracking_number, tracking_url="", request=None):
    fulfillment=FulfillmentRecord.objects.select_for_update().select_related("order").get(pk=fulfillment.pk); _require_fulfillment_actor(actor,fulfillment)
    if fulfillment.status != FulfillmentRecord.Status.PACKED: raise ValidationError("Order must be packed before shipping.")
    if not carrier.strip() or not tracking_number.strip(): raise ValidationError("Carrier and tracking number are required.")
    fulfillment.status=FulfillmentRecord.Status.SHIPPED; fulfillment.carrier=carrier.strip(); fulfillment.tracking_number=tracking_number.strip(); fulfillment.tracking_url=tracking_url; fulfillment.shipped_at=timezone.now(); fulfillment.save()
    _event(fulfillment,fulfillment.status,actor,f"{fulfillment.carrier} · {fulfillment.tracking_number}"); _notify_customer(fulfillment.order,"Order shipped","تم شحن الطلب",f"Order {fulfillment.order.number} has shipped.",f"تم شحن الطلب {fulfillment.order.number}.")
    record_audit_event(actor=actor,action="fulfillment.shipped",instance=fulfillment,metadata={"carrier":carrier},request=request); return fulfillment


@transaction.atomic
def deliver_order(*, fulfillment, actor, request=None):
    fulfillment=FulfillmentRecord.objects.select_for_update().select_related("order").get(pk=fulfillment.pk); _require_fulfillment_actor(actor,fulfillment)
    if fulfillment.status != FulfillmentRecord.Status.SHIPPED: raise ValidationError("Only shipped orders can be delivered.")
    fulfillment.status=FulfillmentRecord.Status.DELIVERED; fulfillment.delivered_at=timezone.now(); fulfillment.save(update_fields=["status","delivered_at","updated_at"]); _event(fulfillment,fulfillment.status,actor)
    _notify_customer(fulfillment.order,"Order delivered","تم تسليم الطلب",f"Order {fulfillment.order.number} was delivered.",f"تم تسليم الطلب {fulfillment.order.number}.")
    record_audit_event(actor=actor,action="fulfillment.delivered",instance=fulfillment,request=request); return fulfillment
