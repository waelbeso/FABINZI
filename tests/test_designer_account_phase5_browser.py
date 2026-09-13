import os
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from apps.artwork.models import Artwork, ArtworkAsset, ArtworkVersion, DesignedProduct
from apps.design.models import GarmentDesign, GarmentDesignVersion
from apps.media.models import MediaAsset
from apps.organizations.models import (
    DesignerProfile,
    Membership,
    OnboardingApplication,
    Organization,
)
from apps.public_profiles.models import ProfessionalPublicState
from apps.public_profiles.services import ensure_public_state
from apps.storefront.models import StoreProduct, Storefront

from .test_designer_portal_browser import _chrome, _no_overflow


User = get_user_model()
ARTIFACT_DIR = Path("artifacts/designer-browser-qa")
REQUIRED = [
    "p5-01-designer-directory-en-desktop-image.png",
    "p5-02-designer-directory-en-desktop-fallback.png",
    "p5-03-designer-directory-en-broken-image-fallback.png",
    "p5-04-designer-directory-ar-rtl-mobile-dark.png",
    "p5-05-designer-public-profile-en-desktop.png",
    "p5-06-designer-public-profile-hero.png",
    "p5-07-designer-public-profile-approved-work.png",
    "p5-08-designer-public-profile-empty-work.png",
    "p5-09-designer-public-profile-profile-fallback.png",
    "p5-10-designer-public-profile-ar-rtl-mobile-dark.png",
]


def _wait(driver):
    return WebDriverWait(driver, 12)


def _shot(driver, name):
    assert name in REQUIRED
    assert _no_overflow(driver), (name, driver.current_url)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    assert driver.save_screenshot(str(ARTIFACT_DIR / name))
    assert (ARTIFACT_DIR / name).exists()


def _focus(driver, element):
    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center', inline:'nearest', behavior:'auto'});",
        element,
    )
    _wait(driver).until(
        lambda _d: bool(
            _d.execute_script(
                """
                const r = arguments[0].getBoundingClientRect();
                return r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;
                """,
                element,
            )
        )
    )


def _position_complete_directory_card(driver, card, fallback):
    driver.execute_script(
        """
        const card = arguments[0];
        const header = document.querySelector('header');
        const headerBottom = header ? Math.max(0, header.getBoundingClientRect().bottom) : 0;
        const targetTop = Math.max(headerBottom + 24, 140);
        const rect = card.getBoundingClientRect();
        const targetY = Math.max(0, window.scrollY + rect.top - targetTop);
        window.scrollTo(0, targetY);
        """,
        card,
    )
    _wait(driver).until(
        lambda _d: bool(
            _d.execute_script(
                """
                const cardRect = arguments[0].getBoundingClientRect();
                const fallbackRect = arguments[1].getBoundingClientRect();
                const header = document.querySelector('header');
                const headerBottom = header ? Math.max(0, header.getBoundingClientRect().bottom) : 0;
                const usableTop = headerBottom + 8;
                const usableBottom = innerHeight - 12;
                return cardRect.top >= usableTop &&
                    cardRect.bottom <= usableBottom &&
                    cardRect.left >= 0 &&
                    cardRect.right <= innerWidth &&
                    fallbackRect.top >= usableTop &&
                    fallbackRect.bottom <= usableBottom &&
                    fallbackRect.left >= 0 &&
                    fallbackRect.right <= innerWidth;
                """,
                card,
                fallback,
            )
        )
    )


def _designer(owner, display_name, *, city="Cairo", region="Cairo Governorate"):
    org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name=display_name,
        email=f"{owner.username}@phase5-browser.test",
        phone="+201033333333",
        city=city,
        region=region,
        country="EG",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    Membership.objects.create(
        organization=org,
        user=owner,
        role=Membership.Role.OWNER,
        is_active=True,
    )
    DesignerProfile.objects.create(
        organization=org,
        studio_name=display_name,
        terms_accepted=True,
        terms_accepted_at=timezone.now(),
    )
    OnboardingApplication.objects.create(
        organization=org,
        status=OnboardingApplication.Status.APPROVED,
        reviewed_at=timezone.now(),
    )
    state = ensure_public_state(org)
    state.public_name_en = display_name
    state.public_name_ar = f"{display_name} عربي"
    state.bio_en = (
        "A public Designer profile created for Phase 5 visual evidence with approved "
        "identity, creative specialization and work."
    )
    state.bio_ar = "ملف مصمم عام للمرحلة الخامسة يعرض الهوية والتخصصات والأعمال المعتمدة."
    state.specializations = [
        "Casualwear",
        "Streetwear",
        "T-Shirt Design",
        "Textile Prints",
        "Graphic Artwork",
        "Pattern Making",
        "Technical Fashion Drawing",
    ]
    state.visibility = ProfessionalPublicState.Visibility.VISIBLE
    state.save()
    return org, state


def _asset(owner, key, public_url, organization):
    return MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id=f"phase5-browser-{key}",
        original_filename=f"{key}.png",
        mime_type="image/png",
        size_bytes=64,
        checksum_sha256="b" * 64,
        access=MediaAsset.Access.PUBLIC,
        uploaded_by=owner,
        metadata={
            "organization_id": organization.pk,
            "designer_public_upload": True,
            "public_url": public_url,
        },
    )


def _public_work(org, owner):
    garment = GarmentDesign.objects.create(
        organization=org,
        title="Signature Draped Day Dress",
        category="Day Dress",
        status=GarmentDesign.Status.APPROVED,
        created_by=owner,
    )
    garment_version = GarmentDesignVersion.objects.create(
        design=garment,
        version_number=1,
        status=GarmentDesignVersion.Status.APPROVED,
        created_by=owner,
    )
    artwork = Artwork.objects.create(
        organization=org,
        title="Botanical Line Artwork",
        status=Artwork.Status.APPROVED,
        created_by=owner,
    )
    artwork_version = ArtworkVersion.objects.create(
        artwork=artwork,
        version_number=1,
        status=ArtworkVersion.Status.APPROVED,
        created_by=owner,
    )
    preview = _asset(
        owner,
        "artwork-preview",
        "/static/brand/fabinzi-icon.svg",
        org,
    )
    ArtworkAsset.objects.create(
        version=artwork_version,
        kind=ArtworkAsset.Kind.PREVIEW,
        media_asset=preview,
        label="Public artwork preview",
    )
    designed = DesignedProduct.objects.create(
        organization=org,
        garment_version=garment_version,
        artwork_version=artwork_version,
        title="Botanical Ready Dress",
        status=DesignedProduct.Status.PUBLISHED,
        created_by=owner,
    )
    store = Storefront.objects.create(
        organization=org,
        slug="phase5-browser-store",
        status=Storefront.Status.PUBLISHED,
        name_en="Phase 5 Browser Store",
    )
    product = StoreProduct.objects.create(
        storefront=store,
        designed_product=designed,
        slug="botanical-ready-dress",
        status=StoreProduct.Status.PUBLISHED,
        title_en="Botanical Ready Dress",
        title_ar="فستان بوتانيكال جاهز",
        base_price="950.00",
        currency="EGP",
    )
    return artwork, product


@pytest.mark.django_db(transaction=True)
def test_designer_phase5_public_presentation_browser_evidence(live_server):
    if os.getenv("CI") != "true":
        pytest.skip("Phase 5 real-browser evidence is CI-only.")

    image_owner = User.objects.create_user(
        username="phase5-browser-image-owner",
        email="phase5-browser-image-owner@example.test",
        password="password12345",
    )
    image_org, image_state = _designer(image_owner, "Idesign Phase 5")
    image_state.profile_image = _asset(
        image_owner,
        "profile",
        "/static/brand/fabinzi-icon.svg",
        image_org,
    )
    image_state.cover_image = _asset(
        image_owner,
        "cover",
        "/static/brand/fabinzi-logo.svg",
        image_org,
    )
    image_state.save(update_fields=["profile_image", "cover_image", "updated_at"])
    artwork, product = _public_work(image_org, image_owner)

    fallback_owner = User.objects.create_user(
        username="phase5-browser-fallback-owner",
        email="phase5-browser-fallback-owner@example.test",
        password="password12345",
    )
    fallback_org, fallback_state = _designer(
        fallback_owner,
        "Fallback Atelier",
        city="Alexandria",
        region="Alexandria",
    )

    broken_owner = User.objects.create_user(
        username="phase5-browser-broken-owner",
        email="phase5-browser-broken-owner@example.test",
        password="password12345",
    )
    broken_org, broken_state = _designer(
        broken_owner,
        "Broken Image Atelier",
        city="Giza",
        region="Giza",
    )
    broken_state.profile_image = _asset(
        broken_owner,
        "broken-profile",
        "/static/phase5-designer-image-does-not-exist.png",
        broken_org,
    )
    broken_state.save(update_fields=["profile_image", "updated_at"])

    empty_owner = User.objects.create_user(
        username="phase5-browser-empty-owner",
        email="phase5-browser-empty-owner@example.test",
        password="password12345",
    )
    empty_org, empty_state = _designer(empty_owner, "Empty Work Atelier")

    driver = _chrome(width=1440, height=1000)
    try:
        wait = _wait(driver)

        driver.get(f"{live_server.url}/designers/?lang=en")
        grid = wait.until(
            EC.visibility_of_element_located((By.ID, "designer-directory-grid"))
        )
        assert grid.is_displayed()
        assert _no_overflow(driver)
        image_card = driver.find_element(By.ID, f"designer-card-{image_state.slug}")
        image = image_card.find_element(By.CSS_SELECTOR, "[data-public-profile-image]")
        wait.until(lambda _d: image.is_displayed())
        assert image.get_attribute("src").endswith("/static/brand/fabinzi-icon.svg")
        assert image_card.find_element(By.CSS_SELECTOR, ".v25-designer-card-cta").is_displayed()
        for item in image_state.specializations:
            assert item in image_card.text
        _focus(driver, image_card)
        _shot(driver, "p5-01-designer-directory-en-desktop-image.png")

        fallback_card = driver.find_element(
            By.ID, f"designer-card-{fallback_state.slug}"
        )
        fallback = fallback_card.find_element(
            By.CSS_SELECTOR, "[data-public-image-fallback]"
        )
        assert fallback.is_displayed() and "DSG" in fallback.text
        assert not fallback_card.find_elements(
            By.CSS_SELECTOR, "[data-public-profile-image]"
        )
        assert "Fallback Atelier" in fallback_card.text
        assert "FABINZI-approved Designer" in fallback_card.text
        assert fallback_card.find_element(
            By.CSS_SELECTOR, ".v25-designer-card-cta"
        ).is_displayed()
        _position_complete_directory_card(driver, fallback_card, fallback)
        _shot(driver, "p5-02-designer-directory-en-desktop-fallback.png")

        broken_card = driver.find_element(By.ID, f"designer-card-{broken_state.slug}")
        broken_img = broken_card.find_element(
            By.CSS_SELECTOR, "[data-public-profile-image]"
        )
        broken_fallback = broken_card.find_element(
            By.CSS_SELECTOR, "[data-public-image-fallback]"
        )
        wait.until(lambda _d: (not broken_img.is_displayed()) and broken_fallback.is_displayed())
        assert broken_img.get_attribute("hidden") is not None
        assert "DSG" in broken_fallback.text
        _focus(driver, broken_card)
        _shot(driver, "p5-03-designer-directory-en-broken-image-fallback.png")

        driver.set_window_size(390, 844)
        driver.get(live_server.url + "/")
        driver.execute_script("localStorage.setItem('fabinzi-theme','dark');")
        driver.get(f"{live_server.url}/designers/?lang=ar")
        wait.until(EC.visibility_of_element_located((By.ID, "designer-directory-grid")))
        html = driver.find_element(By.TAG_NAME, "html")
        assert html.get_attribute("dir") == "rtl"
        assert html.get_attribute("data-theme") == "dark"
        assert _no_overflow(driver)
        ar_image_card = driver.find_element(
            By.ID, f"designer-card-{image_state.slug}"
        )
        ar_link = ar_image_card.find_element(By.CSS_SELECTOR, ".v25-designer-card-cta")
        assert "lang=ar" in ar_link.get_attribute("href")
        _focus(driver, ar_image_card)
        _shot(driver, "p5-04-designer-directory-ar-rtl-mobile-dark.png")

        ar_link.send_keys(Keys.ENTER)
        wait.until(
            EC.visibility_of_element_located((By.ID, "designer-public-hero"))
        )
        assert "lang=ar" in driver.current_url
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        assert "lang=ar" in driver.find_element(
            By.ID, "designer-public-inquiry-cta"
        ).get_attribute("href")
        artwork_link = driver.find_element(
            By.XPATH, f'//a[contains(@href, "/artwork/{artwork.pk}/")]'
        )
        product_link = driver.find_element(
            By.XPATH, f'//a[contains(@href, "/store/{product.storefront.slug}/{product.slug}/")]'
        )
        assert "lang=ar" in artwork_link.get_attribute("href")
        assert "lang=ar" in product_link.get_attribute("href")

        driver.set_window_size(1440, 1000)
        driver.execute_script("localStorage.setItem('fabinzi-theme','light');")
        driver.get(
            f"{live_server.url}/designers/{image_state.slug}/?lang=en"
        )
        cover = wait.until(
            EC.visibility_of_element_located((By.ID, "designer-public-cover"))
        )
        hero = driver.find_element(By.ID, "designer-public-hero")
        assert cover.is_displayed() and hero.is_displayed()
        driver.execute_script("window.scrollTo(0, 0);")
        _shot(driver, "p5-05-designer-public-profile-en-desktop.png")

        _focus(driver, hero)
        assert image_state.public_name_en in hero.text
        assert image_state.bio_en in hero.text
        assert "FABINZI-approved Designer" in hero.text
        assert driver.find_element(By.ID, "designer-public-inquiry-cta").is_displayed()
        _shot(driver, "p5-06-designer-public-profile-hero.png")

        work = driver.find_element(By.ID, "designer-approved-work")
        _focus(driver, work)
        assert "Signature Draped Day Dress" in work.text
        assert "Botanical Line Artwork" in work.text
        assert "Botanical Ready Dress" in work.text
        _shot(driver, "p5-07-designer-public-profile-approved-work.png")

        driver.get(
            f"{live_server.url}/designers/{empty_state.slug}/?lang=en"
        )
        empty_work = wait.until(
            EC.visibility_of_element_located((By.ID, "designer-approved-work"))
        )
        _focus(driver, empty_work)
        assert "No approved public Garment Designs right now." in empty_work.text
        assert "No approved public Artwork right now." in empty_work.text
        assert "No approved public Ready Designed Products right now." in empty_work.text
        assert "—" not in empty_work.text
        _shot(driver, "p5-08-designer-public-profile-empty-work.png")

        driver.get(
            f"{live_server.url}/designers/{fallback_state.slug}/?lang=en"
        )
        fallback_hero = wait.until(
            EC.visibility_of_element_located((By.ID, "designer-public-hero"))
        )
        profile_frame = driver.find_element(By.ID, "designer-profile-frame")
        profile_fallback = profile_frame.find_element(
            By.CSS_SELECTOR, "[data-public-image-fallback]"
        )
        assert profile_fallback.is_displayed() and "DSG" in profile_fallback.text
        assert not profile_frame.find_elements(
            By.CSS_SELECTOR, "[data-public-profile-image]"
        )
        _focus(driver, fallback_hero)
        _shot(driver, "p5-09-designer-public-profile-profile-fallback.png")

        driver.set_window_size(390, 844)
        driver.execute_script("localStorage.setItem('fabinzi-theme','dark');")
        driver.get(
            f"{live_server.url}/designers/{image_state.slug}/?lang=ar"
        )
        wait.until(EC.visibility_of_element_located((By.ID, "designer-public-hero")))
        html = driver.find_element(By.TAG_NAME, "html")
        assert html.get_attribute("dir") == "rtl"
        assert html.get_attribute("data-theme") == "dark"
        assert _no_overflow(driver)
        assert "lang=ar" in driver.find_element(
            By.ID, "designer-public-inquiry-cta"
        ).get_attribute("href")
        driver.execute_script("window.scrollTo(0, 0);")
        _shot(driver, "p5-10-designer-public-profile-ar-rtl-mobile-dark.png")

        assert all((ARTIFACT_DIR / name).exists() for name in REQUIRED)
    finally:
        driver.quit()
