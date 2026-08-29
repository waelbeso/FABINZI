from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404

from apps.media.models import MediaAsset
from apps.media.services import stored_media_response
from .models import Artwork, ArtworkAsset, ArtworkVersion


def public_artwork_preview_media(request, pk):
    asset = get_object_or_404(
        MediaAsset,
        pk=pk,
        access=MediaAsset.Access.PUBLIC,
        mime_type__startswith="image/",
        metadata__artwork_public_derivative=True,
    )
    row = (
        ArtworkAsset.objects.filter(
            media_asset=asset,
            kind=ArtworkAsset.Kind.PREVIEW,
            version__status=ArtworkVersion.Status.APPROVED,
            version__artwork__status=Artwork.Status.APPROVED,
        )
        .select_related("version__artwork")
        .first()
    )
    if not row:
        raise Http404

    payload = stored_media_response(asset)
    if isinstance(payload, str):
        response = HttpResponseRedirect(payload)
        response["Cache-Control"] = "public, max-age=300"
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    response = FileResponse(payload, content_type=asset.mime_type)
    safe_name = asset.original_filename.replace(chr(34), "")
    response["Content-Disposition"] = f'inline; filename="{safe_name}"'
    response["Cache-Control"] = "public, max-age=300"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response
