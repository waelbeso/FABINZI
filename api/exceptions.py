from rest_framework.views import exception_handler as drf_exception_handler


def customer_aware_exception_handler(exc, context):
    """Preserve DRF behavior except for the frozen Customer API 404 envelope."""
    response = drf_exception_handler(exc, context)
    request = context.get("request")
    if response is None or request is None:
        return response
    if request.path.startswith("/api/v1/customer/") and response.status_code == 404:
        from api.customer import _error_message, api_error

        return api_error(
            request,
            "not_found",
            _error_message(request, "not_found"),
            http_status=404,
            headers=getattr(response, "headers", None),
        )
    return response
