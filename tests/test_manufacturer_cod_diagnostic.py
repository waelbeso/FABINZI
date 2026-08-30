import pytest
from django.urls import reverse

from tests.test_manufacturer_portal_acceptance import assigned_job, manufacturer
from apps.organizations.models import Membership


@pytest.mark.django_db
def test_diagnostic_manufacturer_cod_render_contexts(client):
    operator, org, _, _ = manufacturer("cod-diagnostic", role=Membership.Role.OPERATOR)
    data = assigned_job(org, prefix="cod-diagnostic")
    client.force_login(operator)

    response = client.get(reverse("manufacturer-production-detail", args=[data["job"].id]))
    assert response.status_code == 200

    rendered = response.content
    lowered = rendered.lower()
    needle = b"cod"
    occurrences = []
    start = 0
    while True:
        index = lowered.find(needle, start)
        if index < 0:
            break
        left = max(0, index - 100)
        right = min(len(rendered), index + len(needle) + 100)
        occurrences.append(rendered[left:right].decode("utf-8", errors="replace"))
        start = index + 1

    pytest.fail(
        "DIAGNOSTIC ONLY — rendered 'cod' occurrences: "
        f"count={len(occurrences)} contexts={occurrences!r}"
    )
