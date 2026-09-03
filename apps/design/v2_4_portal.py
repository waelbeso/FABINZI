import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from .models import (
    DecorationZone,
    DesignAsset,
    DesignColorway,
    DesignMaterial,
    DesignPointOfMeasure,
    GarmentDesign,
    GarmentDesignVersion,
    SizeChartRow,
)
from .services import require_design_access
from .v2_4_portal_services import (
    attach_colorway_image,
    save_colorway,
    save_decoration_zone_contract,
    save_material,
    save_pattern_requirement,
    save_point_of_measure,
    save_pom_value,
    save_version_policy,
    technical_workspace_state,
)


def _json(value, *, default=None):
    value = (value or "").strip()
    if not value:
        return {} if default is None else default
    try:
        result = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValidationError("Enter valid JSON.") from exc
    if not isinstance(result, (dict, list)):
        raise ValidationError("JSON technical data must be an object or list.")
    return result


def _bool(value):
    return str(value or "").lower() in {"1", "true", "on", "yes"}


def _redirect(design, version):
    return redirect(f"/designer/designs/{design.pk}/technical/?version={version.pk}")


@login_required
def designer_design_technical_workspace(request, pk):
    design = get_object_or_404(GarmentDesign, pk=pk)
    require_design_access(request.user, design)
    versions = design.versions.order_by("-version_number")
    version_id = request.GET.get("version") or request.POST.get("version_id")
    version = get_object_or_404(versions, pk=version_id) if version_id else versions.first()
    if version is None:
        raise ValidationError("Garment Design Version is required.")
    require_design_access(request.user, design, edit=request.method == "POST")

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "save_policy":
                save_version_policy(
                    version=version,
                    actor=request.user,
                    product_class=request.POST.get("product_class"),
                    size_system=request.POST.get("size_system"),
                    decoration_applicability=request.POST.get("decoration_applicability"),
                    requires_3d_source=_bool(request.POST.get("requires_3d_source")),
                    qc_requirements=_json(request.POST.get("qc_requirements")),
                    technical_policy=_json(request.POST.get("technical_policy")),
                    request=request,
                )
            elif action == "save_pom":
                point = None
                if request.POST.get("point_id"):
                    point = get_object_or_404(DesignPointOfMeasure, pk=request.POST["point_id"], version=version)
                save_point_of_measure(
                    version=version,
                    actor=request.user,
                    point=point,
                    symbolic_ref=request.POST.get("symbolic_ref"),
                    name=request.POST.get("name"),
                    unit=request.POST.get("unit"),
                    tolerance_plus=request.POST.get("tolerance_plus"),
                    tolerance_minus=request.POST.get("tolerance_minus"),
                    required=_bool(request.POST.get("required")),
                    sort_order=request.POST.get("sort_order"),
                    request=request,
                )
            elif action == "save_pom_value":
                point = get_object_or_404(DesignPointOfMeasure, pk=request.POST.get("point_id"), version=version)
                size = get_object_or_404(SizeChartRow, pk=request.POST.get("size_id"), version=version)
                save_pom_value(point=point, size=size, actor=request.user, value=request.POST.get("value"), request=request)
            elif action == "save_material":
                material = None
                if request.POST.get("material_id"):
                    material = get_object_or_404(DesignMaterial, pk=request.POST["material_id"], version=version)
                save_material(
                    version=version,
                    actor=request.user,
                    material=material,
                    symbolic_ref=request.POST.get("symbolic_ref"),
                    role=request.POST.get("role"),
                    name=request.POST.get("name"),
                    composition=request.POST.get("composition"),
                    gsm=request.POST.get("gsm"),
                    specifications=_json(request.POST.get("specifications")),
                    sort_order=request.POST.get("sort_order"),
                    request=request,
                )
            elif action == "save_pattern":
                size = get_object_or_404(SizeChartRow, pk=request.POST.get("size_id"), version=version)
                asset = None
                if request.POST.get("pattern_asset_id"):
                    asset = get_object_or_404(DesignAsset, pk=request.POST["pattern_asset_id"], version=version, kind=DesignAsset.Kind.PATTERN)
                save_pattern_requirement(
                    version=version,
                    actor=request.user,
                    size=size,
                    required=True,
                    declared_scale_1_to_1=_bool(request.POST.get("declared_scale_1_to_1")),
                    pattern_asset=asset,
                    notes=request.POST.get("notes"),
                    request=request,
                )
            elif action == "save_colorway":
                colorway = None
                if request.POST.get("colorway_id"):
                    colorway = get_object_or_404(DesignColorway, pk=request.POST["colorway_id"], version=version)
                save_colorway(
                    version=version,
                    actor=request.user,
                    colorway=colorway,
                    symbolic_ref=request.POST.get("symbolic_ref"),
                    name=request.POST.get("name"),
                    hex_color=request.POST.get("hex_color"),
                    sort_order=request.POST.get("sort_order"),
                    request=request,
                )
            elif action == "attach_colorway_image":
                colorway = get_object_or_404(DesignColorway, pk=request.POST.get("colorway_id"), version=version)
                asset = get_object_or_404(DesignAsset, pk=request.POST.get("asset_id"), version=version, kind=DesignAsset.Kind.PRODUCT_IMAGE)
                attach_colorway_image(
                    colorway=colorway,
                    actor=request.user,
                    asset=asset,
                    role=request.POST.get("role"),
                    request=request,
                )
            elif action == "save_zone_contract":
                zone = None
                if request.POST.get("zone_id"):
                    zone = get_object_or_404(DecorationZone, pk=request.POST["zone_id"], version=version)
                methods = [value for value in request.POST.getlist("allowed_methods") if value]
                save_decoration_zone_contract(
                    version=version,
                    actor=request.user,
                    zone=zone,
                    symbolic_ref=request.POST.get("symbolic_ref"),
                    name=request.POST.get("name"),
                    surface=request.POST.get("surface"),
                    allowed_methods=methods,
                    placement={
                        "x": request.POST.get("x"),
                        "y": request.POST.get("y"),
                        "width": request.POST.get("width"),
                        "height": request.POST.get("height"),
                    },
                    max_width_mm=request.POST.get("max_width_mm"),
                    max_height_mm=request.POST.get("max_height_mm"),
                    minimum_dpi=request.POST.get("minimum_dpi"),
                    embroidery_constraints=_json(request.POST.get("embroidery_constraints")),
                    notes=request.POST.get("notes"),
                    request=request,
                )
            else:
                raise ValidationError("Unsupported technical-workspace action.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        else:
            messages.success(request, "Technical definition saved.")
        return _redirect(design, version)

    state = technical_workspace_state(version)
    return render(
        request,
        "designer/design_technical_v2_4.html",
        {
            "design": design,
            "version": version,
            "versions": versions,
            "state": state,
            "can_edit": version.status == GarmentDesignVersion.Status.DRAFT and not hasattr(version, "reference_provenance"),
            "product_classes": GarmentDesignVersion.ProductClass.choices,
            "size_systems": GarmentDesignVersion.SizeSystem.choices,
            "decoration_applicability_choices": GarmentDesignVersion.DecorationApplicability.choices,
            "pom_units": DesignPointOfMeasure.Unit.choices,
            "image_roles": __import__("apps.design.models", fromlist=["DesignColorwayImage"]).DesignColorwayImage.Role.choices,
            "production_methods": DecorationZone.ProductionMethod.choices,
            "pattern_assets": version.assets.filter(kind=DesignAsset.Kind.PATTERN).select_related("media_asset"),
            "product_image_assets": version.assets.filter(kind=DesignAsset.Kind.PRODUCT_IMAGE).select_related("media_asset"),
            "qc_requirements_json": json.dumps(version.qc_requirements or {}, indent=2, ensure_ascii=False),
            "technical_policy_json": json.dumps(version.technical_policy or {}, indent=2, ensure_ascii=False),
        },
    )
