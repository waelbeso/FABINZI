import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from .models import Artwork, ArtworkRegistrationSource
from .services import create_registration_case, require_artwork_access
from .v2_4_services import save_artwork_technical_intent


def _json(value):
    value = (value or "").strip()
    if not value:
        return {}
    try:
        result = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValidationError("Enter valid JSON technical evidence.") from exc
    if not isinstance(result, dict):
        raise ValidationError("Technical evidence must be a JSON object.")
    return result


def _redirect(artwork, version):
    return redirect(f"/designer/artworks/{artwork.pk}/technical/?version={version.pk}")


@login_required
def designer_artwork_technical_workspace(request, pk):
    artwork = get_object_or_404(Artwork, pk=pk)
    require_artwork_access(request.user, artwork, edit=request.method == "POST")
    versions = artwork.versions.order_by("-version_number")
    version_id = request.GET.get("version") or request.POST.get("version_id")
    version = get_object_or_404(versions, pk=version_id) if version_id else versions.first()
    if version is None:
        raise ValidationError("Artwork Version is required.")

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "save_technical_intent":
                save_artwork_technical_intent(
                    version=version,
                    actor=request.user,
                    intended_methods=request.POST.getlist("intended_methods"),
                    color_profile=request.POST.get("color_profile"),
                    production_notes=request.POST.get("production_notes"),
                    resolution_evidence=_json(request.POST.get("resolution_evidence")),
                    embroidery_suitability_evidence=_json(request.POST.get("embroidery_suitability_evidence")),
                    request=request,
                )
            elif action == "create_registration_case":
                source = None
                if request.POST.get("source_id"):
                    source = get_object_or_404(ArtworkRegistrationSource, pk=request.POST["source_id"], is_active=True)
                create_registration_case(
                    version=version,
                    applicant=request.user,
                    source_snapshot=source,
                    procedure_template_key=request.POST.get("procedure_template_key", ""),
                    request=request,
                )
            else:
                raise ValidationError("Unsupported Artwork technical-workspace action.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        else:
            messages.success(request, "Artwork technical workflow updated.")
        return _redirect(artwork, version)

    return render(
        request,
        "designer/artwork_technical_v2_4.html",
        {
            "artwork": artwork,
            "version": version,
            "versions": versions,
            "can_edit": version.status == version.Status.DRAFT,
            "resolution_evidence_json": json.dumps(version.resolution_evidence or {}, indent=2, ensure_ascii=False),
            "embroidery_evidence_json": json.dumps(version.embroidery_suitability_evidence or {}, indent=2, ensure_ascii=False),
            "registration_sources": ArtworkRegistrationSource.objects.filter(is_active=True).order_by("-created_at"),
            "registration_cases": version.registration_cases.select_related("source_snapshot", "reviewed_by").prefetch_related("documents"),
        },
    )
