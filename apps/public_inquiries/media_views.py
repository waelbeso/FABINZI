from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404

from apps.media.services import private_media_response
from .models import PublicInquiryAttachment
from .services import can_view_inquiry


def public_inquiry_attachment_media(request, pk):
    attachment = get_object_or_404(PublicInquiryAttachment.objects.select_related("inquiry__target_organization", "media_asset"), pk=pk)
    if not can_view_inquiry(request, attachment.inquiry):
        raise Http404
    asset = attachment.media_asset
    payload = private_media_response(asset)
    if isinstance(payload, str):
        response = HttpResponseRedirect(payload)
    else:
        response = FileResponse(payload, content_type=asset.mime_type)
        response["Content-Disposition"] = f'inline; filename="{asset.original_filename.replace(chr(34), "")}"'
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    return response
