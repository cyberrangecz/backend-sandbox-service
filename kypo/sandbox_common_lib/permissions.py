from rest_framework.permissions import DjangoModelPermissions, BasePermission


class ModelPermissions(DjangoModelPermissions):
    """Model permission which requires *view_<model_name>* permission for GET request."""
    perms_map = {
        'GET': ['%(app_label)s.view_%(model_name)s'],
        'OPTIONS': [],
        'HEAD': [],
        'POST': ['%(app_label)s.add_%(model_name)s'],
        'PUT': ['%(app_label)s.change_%(model_name)s'],
        'PATCH': ['%(app_label)s.change_%(model_name)s'],
        'DELETE': ['%(app_label)s.delete_%(model_name)s'],
    }


class AllowReadOnViewSandbox(BasePermission):
    """ Simple permission class which requires `view_sandbox` permission for GET request."""
    def has_permission(self, request, view):
        return request.method == "GET" and \
            request.user.has_perm(__package__ + ".view_sandbox")
