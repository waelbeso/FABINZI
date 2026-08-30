from rest_framework.parsers import MultiPartParser

from apps.media.services import STUDIO_IMAGE_MAX_BYTES
from .customer import CustomerStudioUploadAPIView, _error_message, api_error


class FrozenCustomerStudioUploadAPIView(CustomerStudioUploadAPIView):
    """Customer v1 upload contract: multipart images only, hard 10 MB maximum."""

    parser_classes = [MultiPartParser]

    def post(self, request, project_id):
        upload = request.FILES.get("file")
        if upload is not None and (getattr(upload, "size", 0) or 0) > STUDIO_IMAGE_MAX_BYTES:
            return api_error(
                request,
                "upload_error",
                _error_message(request, "upload_error"),
                http_status=413,
                fields={"file": ["The image exceeds the 10 MB Customer Studio limit."]},
            )
        return super().post(request, project_id)
