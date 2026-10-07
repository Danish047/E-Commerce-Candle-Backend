from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    """DRF errors, but a nested {"detail": [...]} from serializers is flattened to a string
    so the storefront can always read `detail` as a message."""
    response = exception_handler(exc, context)
    if response is not None and isinstance(response.data, dict):
        detail = response.data.get("detail")
        if isinstance(detail, list) and detail:
            response.data["detail"] = str(detail[0])
        elif "non_field_errors" in response.data:
            response.data = {"detail": str(response.data["non_field_errors"][0])}
    return response
