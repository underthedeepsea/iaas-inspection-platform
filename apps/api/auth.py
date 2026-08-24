"""Session and group-based authorization for public API views."""

from __future__ import annotations

from collections.abc import Iterable

from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist
from django.http import Http404

from .http import api_error


ROLE_ORDER = ("viewer", "operator", "platform_admin")
_ROLE_RANK = {name: index for index, name in enumerate(ROLE_ORDER)}


def require_session(request):
    """Return ``None`` for an authenticated request, otherwise its 401 response."""

    if getattr(getattr(request, "user", None), "is_authenticated", False):
        return None
    return api_error("AUTH_REQUIRED", "authentication is required", status=401)


def require_role(request, minimum: str):
    """Enforce the viewer < operator < platform_admin hierarchy."""

    session_error = require_session(request)
    if session_error is not None:
        return session_error
    if minimum not in _ROLE_RANK:
        raise ValueError(f"unknown role: {minimum}")
    user = request.user
    if getattr(user, "is_superuser", False):
        return None
    groups = getattr(user, "groups", None)
    if groups is None:
        names = ()
    elif hasattr(groups, "values_list"):
        names = groups.values_list("name", flat=True)
    else:
        names = (getattr(group, "name", group) for group in groups)
    rank = max((_ROLE_RANK.get(name, -1) for name in names), default=-1)
    if rank >= _ROLE_RANK[minimum]:
        return None
    return api_error(
        "PERMISSION_DENIED",
        "the authenticated user does not have the required role",
        status=403,
        details={"required_role": minimum},
    )


def owned_or_404(queryset, user, **lookup):
    """Fetch an object while applying its conventional user/owner scope."""

    scoped = _owned_queryset(queryset, user)
    if hasattr(scoped, "get"):
        try:
            return scoped.get(**lookup)
        except (MultipleObjectsReturned, ObjectDoesNotExist, LookupError, ValueError):
            raise Http404("object does not exist") from None

    for value in scoped:
        if all(getattr(value, key, object()) == expected for key, expected in lookup.items()):
            return value
    raise Http404("object does not exist")


def _owned_queryset(queryset, user):
    """Apply ownership only when the queryset model exposes that relation."""

    model = getattr(queryset, "model", None)
    if model is None:
        return _owned_values(queryset, user)
    fields = {field.name: field for field in model._meta.get_fields()}
    if _is_user_relation(fields.get("user")):
        return queryset.filter(user=user)
    if _is_user_relation(fields.get("owner")):
        return queryset.filter(owner=user)
    if _is_user_relation(fields.get("created_by")):
        return queryset.filter(created_by=user)
    return queryset


def _is_user_relation(field) -> bool:
    return field is not None and getattr(field, "remote_field", None) is not None


def _owned_values(values: Iterable, user):
    result = []
    for value in values:
        owner = getattr(value, "user", getattr(value, "owner", getattr(value, "created_by", None)))
        owner_id = getattr(value, "user_id", getattr(value, "owner_id", getattr(value, "created_by_id", None)))
        if owner is None and owner_id is not None:
            if owner_id == getattr(user, "pk", user):
                result.append(value)
            continue
        if owner is None or owner == user or getattr(owner, "pk", owner) == getattr(user, "pk", user):
            result.append(value)
    return result


__all__ = ["ROLE_ORDER", "owned_or_404", "require_role", "require_session"]
