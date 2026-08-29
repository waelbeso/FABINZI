import os
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from apps.artwork.models import ArtworkAsset, ArtworkReview, IPCase, IPDeclaration
from apps.artwork.services import (
    add_artwork_asset,
    create_artwork,
    create_ip_case,
    review_artwork_version,
    set_ip_declaration,
    submit_artwork_version,
)
from apps.checkout.models import CheckoutSession, CustomerOrder, OrderItem
from apps.design.models import DecorationZone, DesignAsset, GarmentDesign, GarmentDesignVersion, SizeChartRow, TechnicalReview
from apps.design.services import review_version
from apps.finance.models import LedgerEntry, OrderFinance, PayoutProfile, SettlementRequest
from apps.finance.services import organization_account
from apps.manufacturer_marketplace.services import add_capability, get_or_create_listing, publish_listing, submit_quote
from apps.media.designer_services import create_private_designer_asset
from apps.media.models import MediaAsset
from apps.operations.models import FulfillmentRecord, ProductionJob
from apps.organizations.models import DesignerProfile, Membership, OnboardingApplication, Organization
from apps.storefront.models import StoreProduct

from .conftest import VALID_PNG

User = get_user_model()
ARTIFACT_DIR = Path("artifacts/designer-browser-qa")


def _chrome(*, language="en-US,en", width=1440, height=1000):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--window-size={width},{height}")
    options.add_experimental_option("prefs", {"intl.accept_languages": language})
    return webdriver.Chrome(options=options)


def _wait(driver):
    return WebDriverWait(driver, 12)


def _login(driver, live_server, client, user):
    client.force_login(user)
    session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    driver.get(live_server.url + "/")
    driver.add_cookie({"name": settings.SESSION_COOKIE_NAME, "value": session_cookie, "path": "/"})


def _click(driver, by, locator):
    element = _wait(driver).until(EC.element_to_be_clickable((by, locator)))
    ActionChains(driver).scroll_to_element(element).move_to_element(element).pause(0.06).click().perform()
    return element


def _click_element(driver, element):
    ActionChains(driver).scroll_to_element(element).move_to_element(element).pause(0.06).click().perform()
    return element


def _replace(driver, element, value):
    ActionChains(driver).scroll_to_element(element).move_to_element(element).pause(0.04).click().perform()
    element.send_keys(Keys.CONTROL, "a")
    element.send_keys(str(value))


def _shot(driver, name):
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    assert driver.save_screenshot(str(ARTIFACT_DIR / name))


def _no_overflow(driver):
    return bool(driver.execute_script("return document.documentElement.scrollWidth <= window.innerWidth + 1"))


def _section_by_heading(driver, heading):
    heading_element = _wait(driver).until(
        EC.visibility_of_element_located(
            (By.XPATH, f'//section[.//h2[normalize-space(.)="{heading}"]]//h2[normalize-space(.)="{heading}"]')
        )
    )
    return heading_element.find_element(By.XPATH, "./ancestor::section[1]")


def _assert_hidden(form, name, value):
    field = form.find_element(By.CSS_SELECTOR, f'input[type="hidden"][name="{name}"]')
    assert field.get_attribute("value") == str(value)
    return field


def _form_with_action(container, action):
    form = container.find_element(
        By.XPATH,
        f'.//form[.//input[@type="hidden" and @name="action" and @value="{action}"]]',
    )
    _assert_hidden(form, "action", action)
    return form


def _open_details_form(driver, container, summary_text):
    details = container.find_element(
        By.XPATH,
        f'.//details[./summary[normalize-space(.)="{summary_text}"]]',
    )
    summary = details.find_element(By.XPATH, f'./summary[normalize-space(.)="{summary_text}"]')
    _click_element(driver, summary)
    _wait(driver).until(lambda _d: details.get_attribute("open") is not None)
    return details.find_element(By.CSS_SELECTOR, "form")


def _active_designer(owner):
    org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name="Atelier North",
        email="hello@atelier-north.test",
        city="Cairo",
        country="EG",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    DesignerProfile.objects.create(
        organization=org,
        studio_name="Atelier North",
        portfolio_url="https://example.test/atelier",
        terms_accepted=True,
    )
    OnboardingApplication.objects.create(organization=org, status=OnboardingApplication.Status.APPROVED)
    return org


def _approved_garment(owner, staff, org):
    design = GarmentDesign.objects.create(
        organization=org,
        title="Essential Tee",
        description="Approved production base",
        category="apparel",
        status=GarmentDesign.Status.IN_REVIEW,
        created_by=owner,
    )
    version = GarmentDesignVersion.objects.create(
        design=design,
        version_number=1,
        status=GarmentDesignVersion.Status.SUBMITTED,
        summary="Production baseline",
        base_material="180 GSM cotton",
        technical_specs={"fabric": "cotton", "gsm": 180},
        created_by=owner,
        submitted_at=timezone.now(),
    )
    SizeChartRow.objects.create(version=version, size_label="M", measurements={"chest_cm": 52, "length_cm": 72})
    zone = DecorationZone.objects.create(
        version=version,
        name="Front chest",
        method=DecorationZone.Method.BOTH,
        placement={"x": 0.5, "y": 0.36},
        max_width_mm=220,
        max_height_mm=260,
    )
    tech = MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id="legacy-tech-pack.pdf",
        original_filename="tech-pack.pdf",
        mime_type="application/pdf",
        size_bytes=20,
        access=MediaAsset.Access.PRIVATE,
        uploaded_by=owner,
    )
    product_image = MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id="/static/brand/fabinzi-logo.svg",
        original_filename="tee.svg",
        mime_type="image/svg+xml",
        size_bytes=10,
        access=MediaAsset.Access.PUBLIC,
        uploaded_by=owner,
        metadata={"public_url": "/static/brand/fabinzi-logo.svg"},
    )
    DesignAsset.objects.create(version=version, kind=DesignAsset.Kind.TECH_PACK, media_asset=tech, label="Technical pack")
    DesignAsset.objects.create(version=version, kind=DesignAsset.Kind.PRODUCT_IMAGE, media_asset=product_image, label="Product reference")
    review_version(
        version=version,
        reviewer=staff,
        decision=TechnicalReview.Decision.APPROVED,
        notes="Technical definition approved for sourcing.",
    )
    return design, version, zone, product_image


def _approved_artwork(owner, staff, org):
    artwork = create_artwork(
        organization=org,
        actor=owner,
        title="North Wave",
        description="Original geometric artwork",
        tags=["geometric", "wave"],
    )
    version = artwork.versions.get()
    version.metadata = {
        "public_production_methods": ["print", "embroidery"],
        "public_product_types": ["apparel"],
        "public_suitability": "Apparel decoration",
    }
    version.color_profile = "sRGB"
    version.save(update_fields=["metadata", "color_profile"])
    for purpose, kind, name in [
        ("artwork_preview", ArtworkAsset.Kind.PREVIEW, "north-wave-preview.png"),
        ("artwork_source", ArtworkAsset.Kind.SOURCE, "north-wave-source.png"),
        ("artwork_rights_evidence", ArtworkAsset.Kind.RIGHTS_EVIDENCE, "north-wave-rights.png"),
    ]:
        media = create_private_designer_asset(
            upload=SimpleUploadedFile(name, VALID_PNG, content_type="image/png"),
            owner=owner,
            organization=org,
            purpose=purpose,
        )
        add_artwork_asset(version=version, actor=owner, media_asset=media, kind=kind, label=name)
    set_ip_declaration(
        version=version,
        actor=owner,
        rights_basis=IPDeclaration.RightsBasis.ORIGINAL,
        rights_holder_name=org.display_name,
        accepts_ip_policy=True,
    )
    submit_artwork_version(version=version, actor=owner)
    review_artwork_version(
        version=version,
        reviewer=staff,
        decision=ArtworkReview.Decision.APPROVED,
        notes="Approved for public Marketplace use.",
    )
    case = create_ip_case(
        actor=owner,
        artwork=artwork,
        reporter_name="Rights Desk",
        reporter_email="rights@example.test",
        claimant_rights="Review record",
        allegation="Open review example",
    )
    case.status = IPCase.Status.UNDER_REVIEW
    case.save(update_fields=["status"])
    return artwork, version, case


def _manufacturer(owner, name):
    org = Organization.objects.create(
        kind=Organization.Kind.MANUFACTURER,
        display_name=name,
        email=f"{name.lower().replace(' ', '-')}@factory.test",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    listing = get_or_create_listing(organization=org, actor=owner)
    listing.headline_en = f"{name} apparel production"
    listing.headline_ar = f"تصنيع ملابس {name}"
    listing.accepts_rfq = True
    listing.save()
    add_capability(
        listing=listing,
        actor=owner,
        capability_type="cut_sew",
        name="Cut & sew",
        methods=["print", "embroidery"],
        min_quantity=10,
        max_quantity=500,
        lead_time_days=14,
    )
    publish_listing(listing=listing, actor=owner)
    return org


def _create_order_visibility(customer, org, product, variant):
    checkout = CheckoutSession.objects.create(
        customer=customer,
        status="placed",
        subtotal=Decimal("650.00"),
        total=Decimal("650.00"),
        currency="EGP",
    )
    order = CustomerOrder.objects.create(
        checkout=checkout,
        customer=customer,
        designer_organization=org,
        status="confirmed",
        payment_method="cod",
        subtotal=Decimal("650.00"),
        total=Decimal("650.00"),
        currency="EGP",
        shipping_snapshot={"city": "Cairo", "private_address": "not rendered"},
    )
    OrderItem.objects.create(
        order=order,
        store_product=product,
        variant=variant,
        sku=variant.sku,
        title=product.title_en,
        unit_price=Decimal("650.00"),
        quantity=1,
        line_total=Decimal("650.00"),
    )
    ProductionJob.objects.create(order=order, status=ProductionJob.Status.AWAITING_ASSIGNMENT)
    fulfillment = FulfillmentRecord.objects.create(
        order=order,
        status=FulfillmentRecord.Status.SHIPPED,
        carrier="QA Carrier",
        tracking_number="FAB-QA-1001",
        shipped_at=timezone.now(),
    )
    account = organization_account(org, "EGP")
    LedgerEntry.objects.create(
        account=account,
        entry_type=LedgerEntry.EntryType.DESIGNER_EARNING,
        amount=Decimal("520.00"),
        currency="EGP",
        available_at=timezone.now(),
        memo=f"Order {order.number}",
    )
    OrderFinance.objects.create(
        order=order,
        designer_account=account,
        gross_amount=Decimal("650.00"),
        platform_fee=Decimal("65.00"),
        manufacturer_payable=Decimal("65.00"),
        designer_earnings=Decimal("520.00"),
        currency="EGP",
        policy_snapshot={"platform_fee_bps": 1000},
        recognized_at=timezone.now(),
        available_at=timezone.now(),
    )
    PayoutProfile.objects.create(
        organization=org,
        method=PayoutProfile.Method.BANK,
        account_holder=org.display_name,
        destination_hint="•••• 4321",
        status=PayoutProfile.Status.VERIFIED,
    )
    return order, fulfillment


@pytest.mark.django_db(transaction=True)
def test_designer_portal_real_chrome_a_to_g(client, live_server):
    if os.getenv("CI") != "true":
        pytest.skip("Real Chrome Designer QA is CI-only.")

    owner = User.objects.create_user(
        username="designer-browser-owner",
        password="password12345",
        email="owner@atelier.test",
        theme_preference="light",
        language_preference="en",
    )
    collaborator = User.objects.create_user(
        username="designer-browser-collab",
        password="password12345",
        email="collab@atelier.test",
    )
    staff = User.objects.create_user(username="designer-browser-staff", password="password12345", is_staff=True)
    factory_user = User.objects.create_user(username="designer-browser-factory", password="password12345")
    org = _active_designer(owner)
    approved_design, approved_garment, approved_zone, public_media = _approved_garment(owner, staff, org)
    approved_artwork, approved_artwork_version, ip_case = _approved_artwork(owner, staff, org)
    factory = _manufacturer(factory_user, "Nile Works")

    driver = _chrome()
    try:
        _login(driver, live_server, client, owner)
        wait = _wait(driver)

        # A. Dashboard + profile + team use visible portal controls.
        driver.get(f"{live_server.url}/designer/?org={org.pk}&lang=en")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".designer-workspace")))
        assert "Designer workspace" in driver.page_source
        assert _no_overflow(driver)
        _shot(driver, "01-designer-dashboard-desktop-en-light.png")

        _click(driver, By.CSS_SELECTOR, 'a[href^="/designer/profile/"]')
        wait.until(EC.presence_of_element_located((By.ID, "profile-display-name")))
        profile_form = driver.find_element(By.XPATH, '//form[.//*[@id="profile-studio-name"]]')
        _replace(driver, profile_form.find_element(By.ID, "profile-studio-name"), "Atelier North Studio")
        _replace(driver, profile_form.find_element(By.ID, "profile-city"), "New Cairo")
        _click_element(driver, profile_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: Organization.objects.filter(pk=org.pk, city="New Cairo").exists())
        org.refresh_from_db()
        org.designer_profile.refresh_from_db()
        assert org.city == "New Cairo"
        assert org.designer_profile.studio_name == "Atelier North Studio"
        _shot(driver, "02-designer-profile-desktop-en-light.png")

        driver.get(f"{live_server.url}/designer/team/?org={org.pk}&lang=en")
        team_section = _section_by_heading(driver, "Add or update a member")
        team_form = _form_with_action(team_section, "upsert")
        team_form.find_element(By.ID, "team-email").send_keys(collaborator.email)
        Select(team_form.find_element(By.ID, "team-role")).select_by_value(Membership.Role.DESIGNER)
        _click_element(driver, team_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(
            lambda _d: Membership.objects.filter(
                organization=org,
                user=collaborator,
                role=Membership.Role.DESIGNER,
                is_active=True,
            ).exists()
        )
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), collaborator.email))
        _shot(driver, "03-designer-team-desktop-en-light.png")

        # B. Garment Design: create + technical definition + size + real normalized zone.
        driver.get(f"{live_server.url}/designer/designs/?org={org.pk}&lang=en")
        create_design_section = _section_by_heading(driver, "Create Garment Design")
        create_design_form = create_design_section.find_element(By.CSS_SELECTOR, 'form[method="post"]')
        _shot(driver, "04-designer-designs-desktop-en-light.png")
        create_design_form.find_element(By.ID, "id_title").send_keys("Browser Capsule Tee")
        create_design_form.find_element(By.ID, "id_description").send_keys("Chrome-created garment design")
        create_design_form.find_element(By.ID, "id_category").send_keys("apparel")
        _click_element(driver, create_design_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: GarmentDesign.objects.filter(organization=org, title="Browser Capsule Tee").exists())
        browser_design = GarmentDesign.objects.get(organization=org, title="Browser Capsule Tee")
        browser_version = browser_design.versions.get()

        technical_section = wait.until(
            EC.visibility_of_element_located(
                (By.XPATH, '//section[.//input[@name="action" and @value="save_version"]]')
            )
        )
        technical_form = _form_with_action(technical_section, "save_version")
        _assert_hidden(technical_form, "version_id", browser_version.pk)
        _replace(driver, technical_form.find_element(By.ID, "version-summary"), "Browser production definition")
        _replace(driver, technical_form.find_element(By.ID, "version-material"), "Organic cotton")
        _replace(driver, technical_form.find_element(By.ID, "version-specs"), "gsm = 200\nfit = regular")
        _click_element(driver, technical_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(
            lambda _d: GarmentDesignVersion.objects.filter(
                pk=browser_version.pk,
                base_material="Organic cotton",
            ).exists()
        )
        browser_version.refresh_from_db()
        assert browser_version.technical_specs == {"gsm": "200", "fit": "regular"}

        size_chart = wait.until(EC.visibility_of_element_located((By.ID, "size-chart")))
        size_form = _open_details_form(driver, size_chart, "Add size row")
        _assert_hidden(size_form, "action", "save_size")
        _assert_hidden(size_form, "version_id", browser_version.pk)
        size_form.find_element(By.NAME, "size_label").send_keys("M")
        size_form.find_element(By.NAME, "measurements").send_keys("chest_cm = 54\nlength_cm = 73")
        _click_element(driver, size_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: SizeChartRow.objects.filter(version=browser_version, size_label="M").exists())
        size_row = SizeChartRow.objects.get(version=browser_version, size_label="M")
        assert size_row.measurements == {"chest_cm": "54", "length_cm": "73"}
        wait.until(EC.text_to_be_present_in_element((By.ID, "size-chart"), "chest_cm: 54"))

        decoration_zones = wait.until(EC.visibility_of_element_located((By.ID, "decoration-zones")))
        zone_form = _open_details_form(driver, decoration_zones, "Add Decoration Zone")
        _assert_hidden(zone_form, "action", "save_zone")
        _assert_hidden(zone_form, "version_id", browser_version.pk)
        zone_form.find_element(By.NAME, "name").send_keys("Front print")
        Select(zone_form.find_element(By.NAME, "method")).select_by_value("print")
        _replace(driver, zone_form.find_element(By.NAME, "x"), "0.50")
        _replace(driver, zone_form.find_element(By.NAME, "y"), "0.38")
        _replace(driver, zone_form.find_element(By.NAME, "max_width_mm"), "210")
        _replace(driver, zone_form.find_element(By.NAME, "max_height_mm"), "250")
        _click_element(driver, zone_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: DecorationZone.objects.filter(version=browser_version, name="Front print").exists())
        browser_zone = DecorationZone.objects.get(version=browser_version, name="Front print")
        assert browser_zone.placement == {"x": 0.5, "y": 0.38}
        wait.until(EC.text_to_be_present_in_element((By.ID, "decoration-zones"), "Front print"))
        _shot(driver, "05-designer-design-detail-desktop-en-light.png")
        decoration_zones = driver.find_element(By.ID, "decoration-zones")
        zone_heading = decoration_zones.find_element(By.XPATH, './/*[self::h2 or self::h3][contains(normalize-space(.), "Decoration Zones")]')
        ActionChains(driver).scroll_to_element(zone_heading).perform()
        _shot(driver, "06-designer-decoration-zones-desktop-en-light.png")

        # C. Artwork/IP and Designed Product use approved workflow rows; product creation/placement is visible UI.
        driver.get(f"{live_server.url}/designer/artworks/{approved_artwork.pk}/?org={org.pk}&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "North Wave"))
        assert "Approved" in driver.page_source
        private_media = [
            row.media_asset
            for row in approved_artwork_version.assets.select_related("media_asset")
            if row.media_asset.access == MediaAsset.Access.PRIVATE
            and not (row.media_asset.metadata or {}).get("artwork_public_derivative")
        ]
        assert private_media
        assert "/media/designer-private/" in driver.page_source
        assert all(media.provider_asset_id not in driver.page_source for media in private_media)
        assert "Approved public preview" not in driver.page_source
        _shot(driver, "07-designer-artwork-desktop-en-light.png")
        ip_heading = driver.find_element(
            By.XPATH,
            '//*[self::h2 or self::h3][contains(normalize-space(.), "IP cases") or contains(normalize-space(.), "IP Cases")]',
        )
        ActionChains(driver).scroll_to_element(ip_heading).perform()
        assert "rights@example.test" not in driver.page_source
        _shot(driver, "08-designer-ip-desktop-en-light.png")

        driver.get(f"{live_server.url}/designer/products/?org={org.pk}&lang=en")
        create_product_section = _section_by_heading(driver, "Create Designed Product")
        create_product_form = create_product_section.find_element(By.CSS_SELECTOR, 'form[method="post"]')
        create_product_form.find_element(By.NAME, "title").send_keys("North Wave Tee")
        create_product_form.find_element(By.CSS_SELECTOR, 'textarea[name="description"]').send_keys(
            "Approved garment and Artwork combination"
        )
        Select(create_product_form.find_element(By.NAME, "garment_version")).select_by_value(str(approved_garment.pk))
        Select(create_product_form.find_element(By.NAME, "artwork_version")).select_by_value(str(approved_artwork_version.pk))
        _click_element(driver, create_product_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: org.designed_products.filter(title="North Wave Tee").exists())
        designed = org.designed_products.get(title="North Wave Tee")
        if f"/designer/products/{designed.pk}/" not in driver.current_url:
            driver.get(f"{live_server.url}/designer/products/{designed.pk}/?org={org.pk}&lang=en")

        placements = wait.until(EC.visibility_of_element_located((By.ID, "placements")))
        placement_form = _open_details_form(driver, placements, "Add placement")
        _assert_hidden(placement_form, "action", "add_placement")
        Select(placement_form.find_element(By.NAME, "decoration_zone")).select_by_value(str(approved_zone.pk))
        Select(placement_form.find_element(By.NAME, "production_method")).select_by_value("print")
        _replace(driver, placement_form.find_element(By.NAME, "x"), "0.50")
        _replace(driver, placement_form.find_element(By.NAME, "y"), "0.50")
        _replace(driver, placement_form.find_element(By.NAME, "scale"), "0.30")
        _replace(driver, placement_form.find_element(By.NAME, "rotation"), "12")
        _click_element(driver, placement_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(
            lambda _d: designed.placements.filter(
                decoration_zone=approved_zone,
                production_method="print",
            ).exists()
        )
        wait.until(EC.text_to_be_present_in_element((By.ID, "placements"), "Scale 0.3"))
        product_header = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "header.designer-page-head")))
        publish_designed_form = _form_with_action(product_header, "publish")
        _click_element(driver, publish_designed_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(
            lambda _d: designed.__class__.objects.filter(
                pk=designed.pk,
                status=designed.Status.PUBLISHED,
            ).exists()
        )
        designed.refresh_from_db()
        _shot(driver, "09-designer-products-desktop-en-light.png")

        # D. RFQ -> manufacturer invitation -> real submitted quote -> visible selection.
        driver.get(f"{live_server.url}/designer/rfqs/?org={org.pk}&lang=en")
        rfq_create_section = _section_by_heading(driver, "Create RFQ")
        rfq_create_form = rfq_create_section.find_element(By.CSS_SELECTOR, 'form[method="post"]')
        Select(rfq_create_form.find_element(By.NAME, "designed_product")).select_by_value(str(designed.pk))
        rfq_create_form.find_element(By.NAME, "title").send_keys("North Wave production run")
        _replace(driver, rfq_create_form.find_element(By.NAME, "quantity"), "100")
        _click_element(driver, rfq_create_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: org.manufacturer_rfqs.filter(title="North Wave production run").exists())
        rfq = org.manufacturer_rfqs.get(title="North Wave production run")
        if f"/designer/rfqs/{rfq.pk}/" not in driver.current_url:
            driver.get(f"{live_server.url}/designer/rfqs/{rfq.pk}/?org={org.pk}&lang=en")

        open_section = _section_by_heading(driver, "Open RFQ to Manufacturers")
        open_form = _form_with_action(open_section, "open")
        manufacturer_box = open_form.find_element(
            By.CSS_SELECTOR,
            f'input[name="manufacturers"][value="{factory.pk}"]',
        )
        _click_element(driver, manufacturer_box)
        assert manufacturer_box.is_selected()
        _click_element(driver, open_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: rfq.invitations.filter(manufacturer=factory).exists())
        rfq.refresh_from_db()
        invitation = rfq.invitations.get(manufacturer=factory)
        quote = submit_quote(
            invitation=invitation,
            actor=factory_user,
            unit_price="120",
            setup_fee="500",
            sample_fee="100",
            shipping_estimate="250",
            currency="EGP",
            minimum_order_quantity=50,
            production_lead_days=12,
        )
        driver.refresh()
        quote_card = wait.until(
            EC.visibility_of_element_located(
                (
                    By.XPATH,
                    f'//article[contains(@class,"designer-quote")][.//strong[normalize-space(.)="{factory.display_name}"]]'
                )
            )
        )
        select_quote_form = _form_with_action(quote_card, "select_quote")
        _assert_hidden(select_quote_form, "quote_id", quote.pk)
        _click_element(driver, select_quote_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(
            lambda _d: rfq.__class__.objects.filter(
                pk=rfq.pk,
                status=rfq.Status.SELECTED,
            ).exists()
        )
        rfq.refresh_from_db()
        _shot(driver, "10-designer-rfq-quotes-desktop-en-light.png")

        # E. Create Designer Store and a StoreProduct through visible controls, then open the same public customer Product.
        driver.get(f"{live_server.url}/designer/store/?org={org.pk}&lang=en")
        store_setup = _section_by_heading(driver, "Store setup")
        create_store_form = _form_with_action(store_setup, "create")
        create_store_form.find_element(By.NAME, "slug").send_keys("atelier-north")
        create_store_form.find_element(By.NAME, "name_en").send_keys("Atelier North Store")
        create_store_form.find_element(By.NAME, "name_ar").send_keys("متجر أتيليه نورث")
        _click_element(driver, create_store_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: hasattr(org, "storefront"))
        store = org.storefront

        storefront_details = _section_by_heading(driver, "Storefront details")
        publish_store_form = _form_with_action(storefront_details, "publish")
        _click_element(driver, publish_store_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(
            lambda _d: store.__class__.objects.filter(
                pk=store.pk,
                status=store.Status.PUBLISHED,
            ).exists()
        )
        store.refresh_from_db()

        catalog_section = _section_by_heading(driver, "Add catalog product")
        catalog_form = _form_with_action(catalog_section, "create_product")
        Select(catalog_form.find_element(By.NAME, "designed_product")).select_by_value(str(designed.pk))
        catalog_form.find_element(By.NAME, "slug").send_keys("north-wave-tee")
        catalog_form.find_element(By.NAME, "title_en").send_keys("North Wave Tee")
        catalog_form.find_element(By.NAME, "title_ar").send_keys("تيشيرت نورث ويف")
        _replace(driver, catalog_form.find_element(By.NAME, "base_price"), "650")
        Select(catalog_form.find_element(By.NAME, "fulfillment_mode")).select_by_value(StoreProduct.FulfillmentMode.STOCK)
        customization = catalog_form.find_element(By.NAME, "customization_enabled")
        if not customization.is_selected():
            _click_element(driver, customization)
        _click_element(driver, catalog_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: StoreProduct.objects.filter(storefront=store, slug="north-wave-tee").exists())
        product = StoreProduct.objects.get(storefront=store, slug="north-wave-tee")
        if f"/designer/store/products/{product.pk}/" not in driver.current_url:
            driver.get(f"{live_server.url}/designer/store/products/{product.pk}/?org={org.pk}&lang=en")

        variants_section = _section_by_heading(driver, "Variants")
        variant_form = _open_details_form(driver, variants_section, "Add variant")
        _assert_hidden(variant_form, "action", "add_variant")
        variant_form.find_element(By.NAME, "sku").send_keys("NW-TEE-M")
        variant_form.find_element(By.NAME, "size").send_keys("M")
        variant_form.find_element(By.NAME, "color_name").send_keys("Black")
        _replace(driver, variant_form.find_element(By.NAME, "stock_quantity"), "8")
        _click_element(driver, variant_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: product.variants.filter(sku="NW-TEE-M").exists())
        variant = product.variants.get(sku="NW-TEE-M")

        image_section = _section_by_heading(driver, "Public product images")
        image_form = _form_with_action(image_section, "add_image")
        Select(image_form.find_element(By.NAME, "media_asset")).select_by_value(str(public_media.pk))
        _click_element(driver, image_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: product.images.filter(media_asset=public_media).exists())
        product.refresh_from_db()

        store_product_header = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "header.designer-page-head")))
        publish_product_form = _form_with_action(store_product_header, "publish")
        _click_element(driver, publish_product_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(
            lambda _d: StoreProduct.objects.filter(
                pk=product.pk,
                status=StoreProduct.Status.PUBLISHED,
            ).exists()
        )
        product.refresh_from_db()
        _shot(driver, "11-designer-store-desktop-en-light.png")

        store_product_header = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "header.designer-page-head")))
        original_window = driver.current_window_handle
        customer_link = store_product_header.find_element(By.XPATH, './/a[contains(normalize-space(.), "View customer page")]')
        _click_element(driver, customer_link)
        wait.until(lambda d: len(d.window_handles) > 1)
        customer_window = [h for h in driver.window_handles if h != original_window][0]
        driver.switch_to.window(customer_window)
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "North Wave Tee"))
        assert f"/store/{store.slug}/{product.slug}/" in driver.current_url
        driver.close()
        driver.switch_to.window(original_window)

        # F. Real fulfillment + finance visibility; settlement is a visible Designer action.
        customer = User.objects.create_user(
            username="designer-browser-customer",
            password="password12345",
            email="customer-private@example.test",
        )
        order, fulfillment = _create_order_visibility(customer, org, product, variant)
        driver.get(f"{live_server.url}/designer/fulfillment/?org={org.pk}&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "FAB-QA-1001"))
        assert customer.email not in driver.page_source
        _shot(driver, "12-designer-fulfillment-desktop-en-light.png")

        driver.get(f"{live_server.url}/designer/finance/?org={org.pk}&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Designer Earnings"))
        settlement_section = _section_by_heading(driver, "Request settlement")
        settlement_form = _form_with_action(settlement_section, "settlement")
        amount = settlement_form.find_element(By.NAME, "amount")
        _click_element(driver, amount)
        amount.send_keys("100")
        _click_element(driver, settlement_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(
            lambda _d: SettlementRequest.objects.filter(
                organization=org,
                amount=Decimal("100.00"),
            ).exists()
        )
        _shot(driver, "13-designer-finance-desktop-en-light.png")

        # G1. Tablet English regression.
        driver.set_window_size(820, 1180)
        driver.get(f"{live_server.url}/designer/?org={org.pk}&lang=en")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".designer-workspace")))
        assert _no_overflow(driver)
        _shot(driver, "14-designer-dashboard-tablet-en-light.png")

        # G2. Arabic RTL Dark Mobile. GET-only views must never mutate physical zone coordinates.
        original_zone = dict(browser_zone.placement)
        owner.language_preference = "ar"
        owner.theme_preference = "dark"
        owner.save(update_fields=["language_preference", "theme_preference"])
        driver.set_window_size(390, 844)
        driver.get(f"{live_server.url}/designer/?org={org.pk}&lang=ar")
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "html")))
        html = driver.find_element(By.TAG_NAME, "html")
        assert html.get_attribute("dir") == "rtl"
        assert html.get_attribute("data-theme") == "dark"
        assert "مساحة المصمم" in driver.page_source
        assert _no_overflow(driver)
        _shot(driver, "15-designer-dashboard-mobile-ar-rtl-dark.png")

        driver.get(
            f"{live_server.url}/designer/designs/{browser_design.pk}/?org={org.pk}&version={browser_version.pk}&lang=ar"
        )
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Browser Capsule Tee"))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        assert _no_overflow(driver)
        browser_zone.refresh_from_db()
        assert browser_zone.placement == original_zone
        _shot(driver, "16-designer-design-mobile-ar-rtl-dark.png")

        driver.get(f"{live_server.url}/designer/finance/?org={org.pk}&lang=ar")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "أرباح المصمم"))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        assert _no_overflow(driver)
        _shot(driver, "17-designer-finance-mobile-ar-rtl-dark.png")
    finally:
        driver.quit()
