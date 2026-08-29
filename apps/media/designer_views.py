from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404

from apps.organizations.models import Organization
from apps.organizations.services import user_has_org_access
from .models import MediaAsset
from .services import private_media_response


def _designer_asset_org(asset):
    metadata = asset.metadata or {}
    if not metadata.get("designer_private_upload"):
        raise Http404
    try:
        organization_id = int(metadata.get("organization_id"))
    except (TypeError, ValueError):
        raise Http404
    return get_object_or_404(
        Organization,
        pk=organization_id,
        kind=Organization.Kind.DESIGNER,
    )


@login_required
def private_designer_media(request, pk):
    asset = get_object_or_404(MediaAsset, pk=pk, access=MediaAsset.Access.PRIVATE)
    organization = _designer_asset_org(asset)
    if not request.user.is_staff and not user_has_org_access(request.user, organization):
        raise Http404

    payload = private_media_response(asset)
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
