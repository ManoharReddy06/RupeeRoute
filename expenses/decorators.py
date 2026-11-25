from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.core.exceptions import PermissionDenied


def owner_required(view_func):
    """
    Decorator for views that require Owner (Admin) privileges.
    Redirects Viewers with a clear warning notification.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not getattr(request, 'is_owner', False):
            messages.error(request, "Permission Denied: Only Room Owners have write/admin privileges.")
            return redirect('dashboard_monthly')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

