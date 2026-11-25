from .models import Notification


def notifications_context(request):
    """Provides unread notification count and latest activity notifications on all pages."""
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {}

    target_user = request.user
    if hasattr(request.user, 'profile') and request.user.profile.is_viewer and request.user.profile.viewer_of:
        target_user = request.user.profile.viewer_of

    qs = Notification.objects.filter(recipient=target_user).select_related('actor', 'actor__profile', 'group')
    unread_count = qs.filter(is_read=False).count()
    recent = list(qs[:20])

    return {
        'notifications_list': recent,
        'unread_notifications_count': unread_count,
    }
