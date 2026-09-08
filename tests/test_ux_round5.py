import os
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select

from apps.design.models import DecorationZone
from apps.media.models import MediaAsset
from apps.storefront.models import CustomizationElement
from apps.storefront.services import (
    add_customization_element,
    create_studio_project,
    delete_customization_element,
    enable_customization,
    mark_project_ready,
    update_customization_element,
)
from .test_artwork_studio_browser import (
    PRIVATE_UPLOAD_PATH,
    PNG_1X1,
    _assert_no_overflow,
    _chrome,
    _click,
    _creative_catalog,
    _login,
    _shot,
    _start_project_from_studio_entry,
    _url,
    _wait,
)
from .test_artwork_studio_productization import build_catalog, image_upload

User = get_user_model()
ROOT = Path(__file__).resolve().parents[1]


def _two_zone_project(data):
    project = create_studio_project(
        customer=data["customer"],
        product=data["product"],
        variant=data["variant"],
        quantity=1,
    )
    customization = enable_customization(project=project, actor=data["customer"])
    front = add_customization_element(
        customization=customization,
        actor=data["customer"],
        decoration_zone=data["zone"],
        kind=CustomizationElement.Kind.ARTWORK,
        artwork_version=data["version"],
        production_method="print",
        transform={"x": .42, "y": .48, "scale": .2, "rotation": 0},
    )
    back = add_customization_element(
        customization=customization,
        actor=data["customer"],
        decoration_zone=data["print_zone"],
        kind=CustomizationElement.Kind.ARTWORK,
        artwork_version=data["version"],
        production_method="print",
        transform={"x": .58, "y": .52, "scale": .2, "rotation": 10},
    )
    return project, front, back


@pytest.mark.django_db
def test_round5_server_renders_independent_zone_surfaces_and_validates_requested_zone(client):
    data = build_catalog("round5surfaces")
    project, front, back = _two_zone_project(data)
    client.force_login(data["customer"])

    response = client.get(reverse("studio-project", args=[project.pk]) + f"?zone={data['print_zone'].pk}")
    assert response.status_code == 200
    assert response.context["active_zone"].pk == data["print_zone"].pk
    zones = {zone.pk: zone for zone in response.context["zones"]}
    assert [element.pk for element in zones[data["zone"].pk].surface_elements] == [front.pk]
    assert [element.pk for element in zones[data["print_zone"].pk].surface_elements] == [back.pk]

    html = response.content.decode()
    assert html.count("data-zone-surface") == 2
    assert html.count("data-zone-workspace") == 2
    assert html.count('id="zone-workspace"') == 1
    assert f'id="zone-surface-{data["zone"].pk}"' in html
    assert f'id="zone-surface-{data["print_zone"].pk}"' in html
    assert f'value="{data["print_zone"].pk}" data-zone-name="{data["print_zone"].name}"' in html

    for requested in ("not-a-zone", str(data["wrong_zone"].pk), "999999999"):
        fallback = client.get(reverse("studio-project", args=[project.pk]) + f"?zone={requested}")
        assert fallback.status_code == 200
        assert fallback.context["active_zone"].pk == data["zone"].pk


@pytest.mark.django_db
def test_round5_add_actions_and_handled_validation_preserve_zone_redirect(client, tmp_path):
    data = build_catalog("round5redirect")
    project = create_studio_project(customer=data["customer"], product=data["product"], variant=data["variant"])
    enable_customization(project=project, actor=data["customer"])
    client.force_login(data["customer"])
    url = reverse("studio-project", args=[project.pk])
    expected = f"{url}?zone={data['print_zone'].pk}"

    artwork = client.post(
        url,
        {
            "action": "add_artwork",
            "active_zone": data["print_zone"].pk,
            "decoration_zone": data["print_zone"].pk,
            "artwork_version": data["version"].pk,
            "production_method": "print",
        },
    )
    assert artwork.status_code == 302
    assert artwork["Location"] == expected

    text = client.post(
        url,
        {
            "action": "add_text",
            "active_zone": data["print_zone"].pk,
            "decoration_zone": data["print_zone"].pk,
            "text": "Back label",
            "production_method": "print",
        },
    )
    assert text.status_code == 302
    assert text["Location"] == expected

    before = CustomizationElement.objects.filter(customization__project=project).count()
    invalid = client.post(
        url,
        {
            "action": "add_text",
            "active_zone": data["print_zone"].pk,
            "decoration_zone": data["print_zone"].pk,
            "text": "",
            "production_method": "print",
        },
    )
    assert invalid.status_code == 302
    assert invalid["Location"] == expected
    assert CustomizationElement.objects.filter(customization__project=project).count() == before

    with override_settings(MEDIA_ROOT=tmp_path):
        upload = client.post(
            url,
            {
                "action": "upload_image",
                "active_zone": data["print_zone"].pk,
                "decoration_zone": data["print_zone"].pk,
                "production_method": "print",
                "rights_confirmed": "on",
                "file": image_upload("round5-private.png"),
            },
        )
    assert upload.status_code == 302
    assert upload["Location"] == expected
    image = CustomizationElement.objects.get(customization__project=project, kind=CustomizationElement.Kind.IMAGE)
    assert image.decoration_zone_id == data["print_zone"].pk
    assert image.media_asset.access == MediaAsset.Access.PRIVATE
    assert image.media_asset.uploaded_by_id == data["customer"].pk
    assert image.rights_confirmed is True


@pytest.mark.django_db
def test_round5_same_artwork_transform_delete_ready_and_generic_zone_counts(client):
    data = build_catalog("round5independent")
    project, front, back = _two_zone_project(data)
    assert front.artwork_version_id == back.artwork_version_id
    assert front.pk != back.pk
    assert front.decoration_zone_id != back.decoration_zone_id

    back_before = dict(back.transform)
    update_customization_element(
        element=front,
        actor=data["customer"],
        transform={"x": .46, "y": .44, "scale": .18, "rotation": -15},
    )
    front.refresh_from_db()
    back.refresh_from_db()
    assert front.transform == {"x": .46, "y": .44, "scale": .18, "rotation": -15.0}
    assert back.transform == back_before

    delete_customization_element(element=front, actor=data["customer"])
    assert not CustomizationElement.objects.filter(pk=front.pk).exists()
    assert CustomizationElement.objects.filter(pk=back.pk).exists()

    mark_project_ready(project=project, actor=data["customer"])
    client.force_login(data["customer"])
    ready = client.get(reverse("studio-project", args=[project.pk]) + f"?zone={data['print_zone'].pk}")
    assert ready.status_code == 200
    assert ready.context["active_zone"].pk == data["print_zone"].pk
    assert ready.content.decode().count("data-zone-surface") == 2
    assert "data-handle=\"scale\"" not in ready.content.decode()

    one = build_catalog("round5onezone")
    one["print_zone"].delete()
    one_project = create_studio_project(customer=one["customer"], product=one["product"], variant=one["variant"])
    enable_customization(project=one_project, actor=one["customer"])
    client.force_login(one["customer"])
    one_response = client.get(reverse("studio-project", args=[one_project.pk]))
    assert one_response.status_code == 200
    assert one_response.content.decode().count("data-zone-surface") == 1

    many = build_catalog("round5manyzone")
    DecorationZone.objects.create(
        version=many["garment"],
        name="Pocket",
        method=DecorationZone.Method.PRINT,
        placement={"x": .3, "y": .45},
        max_width_mm=80,
        max_height_mm=90,
    )
    many_project = create_studio_project(customer=many["customer"], product=many["product"], variant=many["variant"])
    enable_customization(project=many_project, actor=many["customer"])
    client.force_login(many["customer"])
    many_response = client.get(reverse("studio-project", args=[many_project.pk]))
    assert many_response.status_code == 200
    assert many_response.content.decode().count("data-zone-surface") == 3



def test_round5_source_contract_uses_structural_surfaces_and_per_zone_pointer_geometry():
    template = (ROOT / "templates/storefront/studio_project.html").read_text(encoding="utf-8")
    javascript = (ROOT / "static/js/studio-editor.js").read_text(encoding="utf-8")
    views = (ROOT / "apps/storefront/studio_views.py").read_text(encoding="utf-8")

    assert "data-zone-surface" in template
    assert "data-zone-workspace" in template
    assert "zone.surface_elements" in template
    assert "zone.surface_elements = elements_by_zone[zone.pk]" in views
    assert "_resolve_active_zone" in views
    assert "request.GET.get(\"zone\")" in views
    assert "el.closest('[data-zone-workspace]')" in javascript
    assert "const workspace = document.getElementById('zone-workspace')" not in javascript
    assert "surface.hidden = surface.dataset.zoneId !== option.value" in javascript
    assert "replaceState" in javascript
    assert "privateFileInput.files?.[0]?.name" in javascript
    assert "privateFileInput.value" not in javascript
    assert "innerHTML" not in javascript


@pytest.mark.django_db(transaction=True)
def test_round5_real_chrome_front_back_isolation_sync_upload_mobile_and_rtl(client, live_server):
    if os.getenv("CI") != "true":
        pytest.skip("Real Chrome FABINZI UX Round 5 QA is CI-only.")

    data = _creative_catalog("round5browser")
    back_zone = DecorationZone.objects.create(
        version=data["zone"].version,
        name="Back",
        method=DecorationZone.Method.BOTH,
        placement={"x": .5, "y": .62},
        max_width_mm=320,
        max_height_mm=420,
    )
    customer = User.objects.create_user(
        username="round5-browser-customer",
        password="password12345",
        theme_preference="light",
        language_preference="en",
    )
    PRIVATE_UPLOAD_PATH.write_bytes(PNG_1X1)

    driver = _chrome(width=1440, height=1050)
    try:
        _login(driver, live_server, client, customer)
        wait = _wait(driver)
        driver.get(_url(live_server, "public-store-product", data["store"].slug, data["product"].slug))
        _click(driver, By.ID, "product-customize-link")
        project = _start_project_from_studio_entry(driver, data)
        project_url = _url(live_server, "studio-project", project.pk)

        _click(driver, By.CSS_SELECTOR, "[data-artwork-choice]")
        Select(driver.find_element(By.ID, "artwork-zone")).select_by_value(str(data["zone"].pk))
        Select(driver.find_element(By.ID, "artwork-method")).select_by_value("print")
        _click(driver, By.ID, "add-selected-artwork")
        wait.until(EC.url_contains(f"zone={data['zone'].pk}"))
        wait.until(lambda _d: CustomizationElement.objects.filter(customization__project=project, kind=CustomizationElement.Kind.ARTWORK).count() == 1)
        front = CustomizationElement.objects.get(customization__project=project, kind=CustomizationElement.Kind.ARTWORK)
        assert front.decoration_zone_id == data["zone"].pk
        assert driver.find_element(By.ID, f"zone-surface-{data['zone'].pk}").is_displayed()
        assert not driver.find_element(By.ID, f"zone-surface-{back_zone.pk}").is_displayed()
        _shot(driver, "round5-01-front-en.png")

        _click(driver, By.CSS_SELECTOR, "[data-artwork-choice]")
        Select(driver.find_element(By.ID, "artwork-zone")).select_by_value(str(back_zone.pk))
        wait.until(lambda d: Select(d.find_element(By.ID, "active-zone")).first_selected_option.get_attribute("value") == str(back_zone.pk))
        assert Select(driver.find_element(By.ID, "upload-zone")).first_selected_option.get_attribute("value") == str(back_zone.pk)
        assert Select(driver.find_element(By.ID, "text-zone")).first_selected_option.get_attribute("value") == str(back_zone.pk)
        assert driver.find_element(By.CSS_SELECTOR, f'[data-zone-anchor="{back_zone.pk}"]').get_attribute("aria-current") == "true"
        assert driver.find_element(By.ID, "active-zone-title").text.strip() == "Back"
        assert driver.find_element(By.ID, f"zone-surface-{back_zone.pk}").is_displayed()
        assert not driver.find_element(By.ID, f"zone-surface-{data['zone'].pk}").is_displayed()
        Select(driver.find_element(By.ID, "artwork-method")).select_by_value("print")
        _click(driver, By.ID, "add-selected-artwork")
        wait.until(EC.url_contains(f"zone={back_zone.pk}"))
        wait.until(lambda _d: CustomizationElement.objects.filter(customization__project=project, kind=CustomizationElement.Kind.ARTWORK).count() == 2)
        artworks = list(CustomizationElement.objects.filter(customization__project=project, kind=CustomizationElement.Kind.ARTWORK).order_by("id"))
        front = next(element for element in artworks if element.decoration_zone_id == data["zone"].pk)
        back = next(element for element in artworks if element.decoration_zone_id == back_zone.pk)
        assert front.artwork_version_id == back.artwork_version_id
        assert front.pk != back.pk
        _shot(driver, "round5-02-back-en.png")

        Select(driver.find_element(By.ID, "active-zone")).select_by_value(str(data["zone"].pk))
        wait.until(lambda d: d.find_element(By.ID, f"zone-surface-{data['zone'].pk}").is_displayed())
        _click(driver, By.CSS_SELECTOR, f'[data-element-id="{front.pk}"]')
        back_before = dict(CustomizationElement.objects.get(pk=back.pk).transform)
        x_control = driver.find_element(By.ID, "transform-x")
        driver.execute_script("arguments[0].value='0.42'; arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", x_control)
        wait.until(lambda _d: float(CustomizationElement.objects.get(pk=front.pk).transform["x"]) == 0.42)
        wait.until(lambda d: d.find_element(By.ID, "studio-save-state").get_attribute("data-state") == "saved")
        assert CustomizationElement.objects.get(pk=back.pk).transform == back_before

        Select(driver.find_element(By.ID, "active-zone")).select_by_value(str(back_zone.pk))
        wait.until(lambda d: d.find_element(By.ID, f"zone-surface-{back_zone.pk}").is_displayed())
        assert not driver.find_element(By.ID, "transform-x").is_enabled()
        assert driver.find_element(By.ID, "transform-x").get_attribute("value") == ""
        _click(driver, By.CSS_SELECTOR, f'[data-element-id="{back.pk}"]')
        front_before_back_edit = dict(CustomizationElement.objects.get(pk=front.pk).transform)
        back_x = driver.find_element(By.ID, "transform-x")
        driver.execute_script("arguments[0].value='0.58'; arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", back_x)
        wait.until(lambda _d: float(CustomizationElement.objects.get(pk=back.pk).transform["x"]) == 0.58)
        assert CustomizationElement.objects.get(pk=front.pk).transform == front_before_back_edit

        _click(driver, By.CSS_SELECTOR, '[data-studio-tab="upload"]')
        file_input = wait.until(EC.presence_of_element_located((By.ID, "private-art-file")))
        file_input.send_keys(str(PRIVATE_UPLOAD_PATH))
        wait.until(lambda d: d.find_element(By.ID, "private-art-file-status").text.strip() == PRIVATE_UPLOAD_PATH.name)
        Select(driver.find_element(By.ID, "upload-zone")).select_by_value(str(data["zone"].pk))
        Select(driver.find_element(By.ID, "upload-zone")).select_by_value(str(back_zone.pk))
        wait.until(lambda d: d.find_element(By.ID, f"zone-surface-{back_zone.pk}").is_displayed())
        assert driver.execute_script("return arguments[0].files.length", file_input) == 1
        assert driver.find_element(By.ID, "private-art-file-status").text.strip() == PRIVATE_UPLOAD_PATH.name
        visible_body = driver.find_element(By.TAG_NAME, "body").text
        assert str(PRIVATE_UPLOAD_PATH) not in visible_body
        assert "fakepath" not in visible_body.lower()
        Select(driver.find_element(By.ID, "upload-method")).select_by_value("print")
        _click(driver, By.ID, "rights-confirmed")
        _click(driver, By.CSS_SELECTOR, "#private-upload-form button[type='submit']")
        wait.until(EC.url_contains(f"zone={back_zone.pk}"))
        wait.until(lambda _d: CustomizationElement.objects.filter(customization__project=project, kind=CustomizationElement.Kind.IMAGE).count() == 1)
        private_image = CustomizationElement.objects.get(customization__project=project, kind=CustomizationElement.Kind.IMAGE)
        assert private_image.decoration_zone_id == back_zone.pk
        assert private_image.media_asset.access == MediaAsset.Access.PRIVATE
        assert private_image.rights_confirmed is True
        _shot(driver, "round5-03-upload-back-en.png")

        _click(driver, By.CSS_SELECTOR, '[data-studio-tab="text"]')
        Select(driver.find_element(By.ID, "text-zone")).select_by_value(str(data["zone"].pk))
        wait.until(lambda d: d.find_element(By.ID, f"zone-surface-{data['zone'].pk}").is_displayed())
        text_input = driver.find_element(By.ID, "studio-text")
        text_input.clear()
        text_input.send_keys("Front only")
        Select(driver.find_element(By.ID, "text-method")).select_by_value("print")
        _click(driver, By.CSS_SELECTOR, '[data-studio-pane="text"] button[type="submit"]')
        wait.until(EC.url_contains(f"zone={data['zone'].pk}"))
        text_element = CustomizationElement.objects.get(customization__project=project, kind=CustomizationElement.Kind.TEXT)
        assert text_element.decoration_zone_id == data["zone"].pk
        Select(driver.find_element(By.ID, "active-zone")).select_by_value(str(back_zone.pk))
        wait.until(lambda d: d.find_element(By.ID, f"zone-surface-{back_zone.pk}").is_displayed())
        assert not driver.find_element(By.CSS_SELECTOR, f'[data-element-id="{text_element.pk}"]').is_displayed()

        driver.refresh()
        wait.until(lambda d: Select(d.find_element(By.ID, "active-zone")).first_selected_option.get_attribute("value") == str(back_zone.pk))
        assert driver.find_element(By.ID, f"zone-surface-{back_zone.pk}").is_displayed()

        driver.set_window_size(390, 844)
        driver.get(project_url + f"?zone={back_zone.pk}&lang=en")
        wait.until(EC.presence_of_element_located((By.ID, "studio-editor")))
        assert driver.execute_script("return Array.from(document.querySelectorAll('[data-zone-surface]')).filter(x => !x.hidden).length") == 1
        assert driver.find_element(By.ID, f"zone-surface-{back_zone.pk}").is_displayed()
        _assert_no_overflow(driver)
        _shot(driver, "round5-04-mobile-en.png")

        front_transform = dict(CustomizationElement.objects.get(pk=front.pk).transform)
        back_transform = dict(CustomizationElement.objects.get(pk=back.pk).transform)
        driver.set_window_size(1440, 1050)
        driver.get(project_url + f"?zone={data['zone'].pk}&lang=ar")
        wait.until(EC.presence_of_element_located((By.ID, "studio-editor")))
        html = driver.find_element(By.TAG_NAME, "html")
        assert html.get_attribute("lang") == "ar"
        assert html.get_attribute("dir") == "rtl"
        workspace = driver.find_element(By.ID, "zone-workspace")
        assert driver.execute_script("return getComputedStyle(arguments[0]).direction", workspace) == "ltr"
        assert CustomizationElement.objects.get(pk=front.pk).transform == front_transform
        assert CustomizationElement.objects.get(pk=back.pk).transform == back_transform
        _assert_no_overflow(driver)
        _shot(driver, "round5-05-ar-rtl-front.png")

        Select(driver.find_element(By.ID, "active-zone")).select_by_value(str(back_zone.pk))
        wait.until(lambda d: d.find_element(By.ID, f"zone-surface-{back_zone.pk}").is_displayed())
        workspace = driver.find_element(By.ID, "zone-workspace")
        assert driver.execute_script("return getComputedStyle(arguments[0]).direction", workspace) == "ltr"
        assert CustomizationElement.objects.get(pk=front.pk).transform == front_transform
        assert CustomizationElement.objects.get(pk=back.pk).transform == back_transform
        _assert_no_overflow(driver)
        _shot(driver, "round5-06-ar-rtl-back.png")
    finally:
        driver.quit()
