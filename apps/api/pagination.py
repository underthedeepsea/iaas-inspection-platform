"""Bounded, consistent list responses."""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.http import JsonResponse

from .http import APIRequestError, api_error, parse_positive_int


DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100


def paginate(queryset, request, serializer: Callable) -> JsonResponse:
    """Serialize one bounded page from a QuerySet or an in-memory iterable."""

    try:
        page = parse_positive_int(request.GET.get("page"), default=DEFAULT_PAGE)
        max_page_size = int(getattr(settings, "API_MAX_PAGE_SIZE", MAX_PAGE_SIZE))
        page_size = parse_positive_int(
            request.GET.get("page_size"),
            default=DEFAULT_PAGE_SIZE,
            maximum=max_page_size,
        )
    except (APIRequestError, TypeError, ValueError) as error:
        if isinstance(error, APIRequestError):
            return api_error(error.code, error.message, status=400, details=error.details)
        return api_error("VALIDATION_ERROR", "pagination parameters are invalid", status=400)

    count = getattr(queryset, "count", None)
    total = count() if callable(count) and hasattr(queryset, "model") else len(queryset)
    start = (page - 1) * page_size
    values = queryset[start : start + page_size]
    items = [serializer(value) for value in values]
    return JsonResponse(
        {"items": items, "page": page, "page_size": page_size, "total": total}
    )


__all__ = ["DEFAULT_PAGE", "DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "paginate"]
