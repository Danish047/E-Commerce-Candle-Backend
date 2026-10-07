from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsStaff(BasePermission):
    message = "Staff access only."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_active and u.is_staff)


class IsOwner(BasePermission):
    message = "Only the store owner can do this."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_active and u.is_superuser)


class StaffReadOwnerWrite(BasePermission):
    message = "Only the store owner can change this."

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated and u.is_active and u.is_staff):
            return False
        return request.method in SAFE_METHODS or u.is_superuser
