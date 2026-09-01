from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.artwork.models import Artwork
from apps.design.models import GarmentDesign
from apps.organizations.models import Organization
from .services import (
    ARTWORK_SLOT_STATUSES,
    DESIGN_SLOT_STATUSES,
    assert_designer_slot_available,
    ensure_subscription_for_organization,
)


@receiver(post_save, sender=Organization, dispatch_uid="v2_3_ensure_professional_subscription")
def ensure_professional_subscription_on_activation(sender, instance, **kwargs):
    if instance.kind not in {Organization.Kind.DESIGNER, Organization.Kind.MANUFACTURER}:
        return
    if instance.verification_status != Organization.VerificationStatus.ACTIVE:
        return
    ensure_subscription_for_organization(instance)


@receiver(pre_save, sender=GarmentDesign, dispatch_uid="v2_3_designer_design_slots")
def enforce_designer_design_slots(sender, instance, **kwargs):
    if instance.status not in DESIGN_SLOT_STATUSES or not instance.pk:
        return
    previous = GarmentDesign.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
    if previous in DESIGN_SLOT_STATUSES:
        return
    assert_designer_slot_available(organization=instance.organization, kind="design", object_id=instance.pk)


@receiver(pre_save, sender=Artwork, dispatch_uid="v2_3_designer_artwork_slots")
def enforce_designer_artwork_slots(sender, instance, **kwargs):
    if instance.status not in ARTWORK_SLOT_STATUSES or not instance.pk:
        return
    previous = Artwork.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
    if previous in ARTWORK_SLOT_STATUSES:
        return
    assert_designer_slot_available(organization=instance.organization, kind="artwork", object_id=instance.pk)
