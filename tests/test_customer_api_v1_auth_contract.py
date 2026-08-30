from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

User = get_user_model()


def _login(client, username, password="password12345"):
    response = client.post(
        reverse("v1:customer:login"),
        {"username": username, "password": password},
        format="json",
    )
    assert response.status_code == 200, response.data
    return response.data


def _authorized(access):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


@pytest.mark.django_db
def test_bootstrap_is_public_and_truthful_about_account_limitations():
    response = APIClient().get(reverse("v1:customer:bootstrap"))
    assert response.status_code == 200
    assert response.data["contract"] == "FABINZI Customer API v1"
    assert response.data["backend_version"] == "1.0.0"
    assert response.data["authentication"] == {
        "scheme": "Bearer",
        "access_token_seconds": 900,
        "refresh_token_seconds": 2592000,
        "refresh_rotation": True,
        "refresh_reuse_revoked": True,
    }
    assert response.data["account_capabilities"] == {
        "signup": False,
        "email_verification": False,
        "account_activation": False,
        "password_reset": False,
        "social_login": False,
    }
    assert response.data["pagination"] == {
        "strategy": "page_number",
        "default_page_size": 20,
        "max_page_size": 50,
    }
    assert response.data["uploads"]["max_bytes"] == 10 * 1024 * 1024
    assert response.data["uploads"]["private_by_default"] is True


@pytest.mark.django_db
def test_login_me_and_preferences_use_bearer_without_internal_fields():
    user = User.objects.create_user(
        username="mobile-customer",
        password="password12345",
        email="mobile@example.test",
        first_name="Mobile",
        last_name="Customer",
    )
    data = _login(APIClient(), user.username)
    assert data["token_type"] == "Bearer"
    assert data["access"] and data["refresh"]
    assert data["access_expires_in"] == 900
    assert data["refresh_expires_in"] == 2592000

    client = _authorized(data["access"])
    me = client.get(reverse("v1:customer:me"))
    assert me.status_code == 200
    assert me.data == {
        "id": user.pk,
        "username": "mobile-customer",
        "display_name": "Mobile Customer",
        "first_name": "Mobile",
        "last_name": "Customer",
        "email": "mobile@example.test",
        "language": "en",
        "theme": "system",
        "account_state": "active",
    }
    serialized = str(me.data).lower()
    for forbidden in ("password", "is_staff", "is_superuser", "mfa", "otp", "permissions"):
        assert forbidden not in serialized

    updated = client.patch(reverse("v1:customer:me"), {"language": "ar", "theme": "dark"}, format="json")
    assert updated.status_code == 200
    assert updated.data["language"] == "ar"
    assert updated.data["theme"] == "dark"
    user.refresh_from_db()
    assert user.language_preference == "ar" and user.theme_preference == "dark"


@pytest.mark.django_db
def test_session_auth_is_not_accepted_on_customer_private_routes():
    user = User.objects.create_user(username="session-only", password="password12345")
    client = APIClient()
    client.force_authenticate(user=user)
    # force_authenticate bypasses authentication classes; use the Django session instead.
    client.force_authenticate(user=None)
    client.login(username="session-only", password="password12345")
    response = client.get(reverse("v1:customer:me"))
    assert response.status_code == 401
    assert response.data["error"]["code"] == "authentication_required"


@pytest.mark.django_db
def test_invalid_credentials_and_inactive_login_are_indistinguishable():
    active = User.objects.create_user(username="active-login", password="password12345")
    inactive = User.objects.create_user(username="inactive-login", password="password12345", is_active=False)
    client = APIClient()
    wrong = client.post(reverse("v1:customer:login"), {"username": active.username, "password": "wrong-password"}, format="json")
    inactive_result = client.post(reverse("v1:customer:login"), {"username": inactive.username, "password": "password12345"}, format="json")
    assert wrong.status_code == inactive_result.status_code == 401
    assert wrong.data["error"]["code"] == inactive_result.data["error"]["code"] == "invalid_credentials"
    assert set(wrong.data["error"]) == {"code", "message", "fields", "request_id"}


@pytest.mark.django_db
def test_invalid_and_expired_access_tokens_use_stable_401_envelope():
    user = User.objects.create_user(username="token-errors", password="password12345")
    invalid = _authorized("not-a-jwt").get(reverse("v1:customer:me"))
    assert invalid.status_code == 401
    assert invalid.data["error"]["code"] == "invalid_token"

    token = AccessToken.for_user(user)
    token.set_exp(lifetime=timedelta(seconds=-1))
    expired = _authorized(str(token)).get(reverse("v1:customer:me"))
    assert expired.status_code == 401
    assert expired.data["error"]["code"] == "token_expired"


@pytest.mark.django_db
def test_refresh_rotates_and_blacklists_previous_refresh():
    user = User.objects.create_user(username="rotate-refresh", password="password12345")
    client = APIClient()
    tokens = _login(client, user.username)
    first_refresh = tokens["refresh"]

    rotated = client.post(reverse("v1:customer:refresh"), {"refresh": first_refresh}, format="json")
    assert rotated.status_code == 200
    assert rotated.data["access"]
    assert rotated.data["refresh"] and rotated.data["refresh"] != first_refresh

    reused = client.post(reverse("v1:customer:refresh"), {"refresh": first_refresh}, format="json")
    assert reused.status_code == 401
    assert reused.data["error"]["code"] == "invalid_refresh_token"


@pytest.mark.django_db
def test_refresh_rejects_user_deactivated_after_login():
    user = User.objects.create_user(username="later-inactive", password="password12345")
    client = APIClient()
    tokens = _login(client, user.username)
    user.is_active = False
    user.save(update_fields=["is_active"])
    response = client.post(reverse("v1:customer:refresh"), {"refresh": tokens["refresh"]}, format="json")
    assert response.status_code == 401
    assert response.data["error"]["code"] == "invalid_refresh_token"


@pytest.mark.django_db
def test_logout_revokes_only_presented_device_refresh_token():
    user = User.objects.create_user(username="multi-device", password="password12345")
    public = APIClient()
    device_a = _login(public, user.username)
    device_b = _login(public, user.username)

    auth_a = _authorized(device_a["access"])
    logout = auth_a.post(reverse("v1:customer:logout"), {"refresh": device_a["refresh"]}, format="json")
    assert logout.status_code == 204

    revoked = public.post(reverse("v1:customer:refresh"), {"refresh": device_a["refresh"]}, format="json")
    still_valid = public.post(reverse("v1:customer:refresh"), {"refresh": device_b["refresh"]}, format="json")
    assert revoked.status_code == 401
    assert still_valid.status_code == 200


@pytest.mark.django_db
def test_logout_is_idempotent_for_an_already_revoked_refresh_token():
    user = User.objects.create_user(username="logout-idempotent", password="password12345")
    public = APIClient()
    tokens = _login(public, user.username)
    auth = _authorized(tokens["access"])
    first = auth.post(reverse("v1:customer:logout"), {"refresh": tokens["refresh"]}, format="json")
    second = auth.post(reverse("v1:customer:logout"), {"refresh": tokens["refresh"]}, format="json")
    assert first.status_code == second.status_code == 204
