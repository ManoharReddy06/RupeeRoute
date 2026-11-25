from .models import UserProfile, UserRole


class RoleMiddleware:
    """
    Attaches role attributes to each incoming request:
    - request.user_role: 'OWNER', 'VIEWER', or 'ANONYMOUS'
    - request.is_owner: bool
    - request.is_viewer: bool
    - request.user_profile: UserProfile instance or None
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            if request.user.is_superuser:
                request.user_role = UserRole.OWNER
                request.is_owner = True
                request.is_viewer = False
                request.user_profile = getattr(request.user, 'profile', None)
            else:
                profile = getattr(request.user, 'profile', None)
                if profile:
                    request.user_role = profile.role
                    request.is_owner = profile.role == UserRole.OWNER
                    request.is_viewer = profile.role == UserRole.VIEWER
                    request.user_profile = profile
                else:
                    # Default fallback
                    request.user_role = UserRole.VIEWER
                    request.is_owner = False
                    request.is_viewer = True
                    request.user_profile = None
        else:
            request.user_role = 'ANONYMOUS'
            request.is_owner = False
            request.is_viewer = False
            request.user_profile = None

        response = self.get_response(request)
        return response

