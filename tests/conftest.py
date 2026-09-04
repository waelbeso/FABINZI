import io
import sys
from datetime import timedelta

import pytest
from PIL import Image
from django.utils import timezone


def _png_bytes():
    buffer = io.BytesIO()
    Image.new("RGBA", (4, 4), (36, 44, 55, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


VALID_PNG = _png_bytes()


@pytest.fixture(autouse=True)
def _valid_png_upload_bytes(monkeypatch):
    """Keep image-upload fixtures genuinely decodable by the installed Pillow.

    The security/browser modules expose a PNG_1X1 constant only as a compact
    source for real multipart upload tests. Replace those bytes at runtime with
    a PNG produced by the same Pillow installation used by the application.
    """
    for module in list(sys.modules.values()):
        if module is not None and hasattr(module, "PNG_1X1"):
            monkeypatch.setattr(module, "PNG_1X1", VALID_PNG)


@pytest.fixture(autouse=True)
def _manufacturer_team_permission_test_has_explicit_pro_capacity(request, monkeypatch):
    """Keep the role-permission regression independent from Starter seat quota.

    This one test verifies owner/manager role boundaries and needs two non-owner
    seats. Give its helper-created Organization a legitimate active Manufacturer
    Pro subscription before the test exercises membership mutation. Production
    Starter quota enforcement remains untouched and is covered separately.
    """
    if request.node.nodeid != "tests/test_manufacturer_portal_acceptance.py::test_team_owner_protection_and_role_permissions":
        return

    module = request.node.module
    original_manufacturer = module.manufacturer

    def manufacturer_with_pro_capacity(*args, **kwargs):
        result = original_manufacturer(*args, **kwargs)
        _owner, organization, _profile, _application = result

        from apps.subscriptions.models import OrganizationSubscription
        from apps.subscriptions.services import get_effective_plan, plan_snapshot, price_snapshot

        now = timezone.now()
        pro = get_effective_plan("manufacturer_pro", at=now)
        OrganizationSubscription.objects.create(
            organization=organization,
            current_plan=pro,
            status=OrganizationSubscription.Status.ACTIVE,
            started_at=now,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
            policy_snapshot=plan_snapshot(pro),
            price_snapshot=price_snapshot(pro),
        )
        return result

    monkeypatch.setattr(module, "manufacturer", manufacturer_with_pro_capacity)
