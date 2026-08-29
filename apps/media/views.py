from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404

from .models import MediaAsset
from .services import private_media_response


@login_required
def private_studio_media(request, pk):
    asset = get_object_or_404(MediaAsset, pk=pk, access=MediaAsset.Access.PRIVATE)
    if not (asset.metadata or {}).get("studio_private_upload"):
        raise Http404
    if not request.user.is_staff and asset.uploaded_by_id != request.user.pk:
        raise Http404

    payload = private_media_response(asset)
    if isinstance(payload, str):
        response = HttpResponseRedirect(payload)
        response["Cache-Control"] = "private, no-store"
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        response["Referrer-Policy"] = "no-referrer"
        return response

    response = FileResponse(payload, content_type=asset.mime_type)
    response["Content-Disposition"] = f'inline; filename="{asset.original_filename.replace(chr(34), "")}"'
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    return response
