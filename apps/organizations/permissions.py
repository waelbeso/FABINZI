from rest_framework.permissions import BasePermission
from .models import Membership


class IsBusinessMember(BasePermission):
    message = "You do not have access to this business."

    def has_object_permission(self, request, view, obj):
        organization = getattr(obj, "organization", obj)
        return Membership.objects.filter(
            organization=organization, user=request.user, is_active=True
        ).exists() or request.user.is_superuser
