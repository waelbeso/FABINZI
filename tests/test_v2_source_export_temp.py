from pathlib import Path
import shutil


def test_export_v2_correction_sources_for_owner_authorized_work_branch():
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts" / "browser-qa" / "v2-correction-source-export"
    paths = [
        ".github/workflows/ci.yml",
        "apps/organizations/admin.py",
        "apps/organizations/designer_services.py",
        "apps/organizations/manufacturer_services.py",
        "apps/organizations/migrations/0003_public_profile_revision.py",
        "apps/organizations/models.py",
        "apps/organizations/public_profile_services.py",
        "apps/organizations/services.py",
        "apps/platform_ops/maneg_services.py",
        "apps/platform_ops/maneg_views.py",
        "templates/admin/organizations/publicprofilerevision/change_form.html",
        "templates/maneg/organization_detail.html",
        "tests/test_designer_portal_acceptance_core.py",
        "tests/test_designer_portal_browser.py",
        "tests/test_maneg_control_center.py",
        "tests/test_manufacturer_portal_acceptance.py",
        "tests/test_manufacturer_portal_browser.py",
        "tests/test_v2_applications_organizations.py",
    ]
    for relative in paths:
        source = root / relative
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    assert all((output / relative).is_file() for relative in paths)
