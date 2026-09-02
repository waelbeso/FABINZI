from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import record_audit_event
from .models import ArtworkVersion
from .services import require_artwork_draft


@transaction.atomic
def save_artwork_technical_intent(
    *,
    version,
    actor,
    intended_methods,
    color_profile="",
    production_notes="",
    resolution_evidence=None,
    embroidery_suitability_evidence=None,
    request=None,
):
    """Creator-editable technical intent; staff technical-check state is separate."""
    require_artwork_draft(version, actor)
    methods = list(dict.fromkeys(intended_methods or []))
    valid = {"dtf", "dtg", "embroidery"}
    if not methods or set(methods) - valid:
        raise ValidationError({"intended_methods": "Choose DTF, DTG and/or Embroidery."})
    version.intended_methods = methods
    version.color_profile = str(color_profile or "").strip()
    version.production_notes = str(production_notes or "").strip()
    version.resolution_evidence = resolution_evidence or {}
    version.embroidery_suitability_evidence = embroidery_suitability_evidence or {}
    version.technical_check_status = ArtworkVersion.TechnicalCheckStatus.NOT_CHECKED
    version.technical_check_result = {}
    version.full_clean()
    version.save(
        update_fields=[
            "intended_methods",
            "color_profile",
            "production_notes",
            "resolution_evidence",
            "embroidery_suitability_evidence",
            "technical_check_status",
            "technical_check_result",
        ]
    )
    record_audit_event(
        actor=actor,
        action="artwork.technical_intent.updated",
        instance=version,
        metadata={"artwork_id": version.artwork_id, "intended_methods": methods},
        request=request,
    )
    return version
