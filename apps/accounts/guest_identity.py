import secrets

GUEST_SESSION_KEY = "fabinzi_guest_identity"


def ensure_guest_identity(request):
    """Return a stable opaque identity for an anonymous browser session.

    The value is stored only inside Django's server-side session. It is not a
    User, business membership, authorization credential, or public identifier.
    Requests constructed outside SessionMiddleware (for example direct error
    handler tests) intentionally skip guest-token creation.
    """

    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return None

    session = getattr(request, "session", None)
    if session is None:
        return None

    identity = session.get(GUEST_SESSION_KEY)
    if not identity:
        identity = secrets.token_urlsafe(32)
        session[GUEST_SESSION_KEY] = identity
    return identity
