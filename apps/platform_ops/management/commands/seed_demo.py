from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.artwork.models import (
    Artwork,
    ArtworkAsset,
    ArtworkPlacement,
    ArtworkVersion,
    DesignedProduct,
    IPDeclaration,
)
from apps.checkout.models import CheckoutSession
from apps.design.models import DecorationZone, DesignAsset, GarmentDesign, GarmentDesignVersion, SizeChartRow
from apps.integrations.models import IntegrationConfig
from apps.manufacturer_marketplace.models import (
    ManufacturerCapability,
    ManufacturerListing,
    ManufacturerQuote,
    ManufacturerSelection,
    RFQ,
    RFQInvitation,
)
from apps.media.models import MediaAsset
from apps.organizations.models import (
    DesignerProfile,
    ManufacturerProfile,
    Membership,
    OnboardingApplication,
    Organization,
)
from apps.storefront.models import (
    CustomerCustomization,
    CustomizationElement,
    ProductVariant,
    StoreProduct,
    StoreProductImage,
    Storefront,
    StudioProject,
)
from apps.subscriptions.models import ArtworkPlanEntitlementState, DesignPlanEntitlementState
from apps.subscriptions.services import ensure_subscription_for_organization


DEMO_PREFIX = "FABINZI Demo"


class Command(BaseCommand):
    help = "Create or reconcile the manually-invoked FABINZI QA demo dataset."

    def handle(self, *args, **options):
        if not settings.FABINZI_DEMO_SEED_ENABLED:
            raise CommandError("Demo seeding is disabled. Set FABINZI_DEMO_SEED_ENABLED=true and run this command manually.")

        passwords = {
            "admin": settings.DEMO_ADMIN_PASSWORD,
            "designer": settings.DEMO_DESIGNER_PASSWORD,
            "manufacturer": settings.DEMO_MANUFACTURER_PASSWORD,
            "customer": settings.DEMO_CUSTOMER_PASSWORD,
        }
        missing = [name for name, value in passwords.items() if not value]
        if missing:
            raise CommandError("Missing demo password environment variables for: " + ", ".join(missing))

        with transaction.atomic():
            data = self._seed(passwords)

        self.stdout.write(self.style.SUCCESS("FABINZI demo seed complete."))
        self.stdout.write(f"Designer: {data['designer'].email}")
        self.stdout.write(f"Manufacturer: {data['manufacturer'].email}")
        self.stdout.write(f"Customer: {data['customer'].email}")
        self.stdout.write("Passwords are sourced only from environment variables and are never printed.")

    def _user(self, username, email, password, *, first_name, last_name, staff=False, superuser=False, language="en", theme="system"):
        User = get_user_model()
        user, _ = User.objects.get_or_create(username=username, defaults={"email": email})
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.is_active = True
        user.is_staff = staff
        user.is_superuser = superuser
        user.language_preference = language
        user.theme_preference = theme
        user.set_password(password)
        user.save()
        return user

    def _organization(self, *, kind, name, owner, email, city, address, website, phone):
        org = Organization.objects.filter(kind=kind, display_name=name).first()
        if not org:
            org = Organization(kind=kind, display_name=name, created_by=owner, email=email)
        org.legal_name = f"{name} LLC"
        org.email = email
        org.phone = phone
        org.website = website
        org.address_line1 = address
        org.city = city
        org.region = "Cairo"
        org.country = "EG"
        org.verification_status = Organization.VerificationStatus.ACTIVE
        org.full_clean()
        org.save()
        membership, _ = Membership.objects.get_or_create(organization=org, user=owner, defaults={"role": Membership.Role.OWNER})
        membership.role = Membership.Role.OWNER
        membership.is_active = True
        membership.full_clean()
        membership.save()
        application, _ = OnboardingApplication.objects.get_or_create(organization=org)
        application.status = OnboardingApplication.Status.APPROVED
        application.review_notes = "Approved QA demo organization."
        application.reviewed_at = application.reviewed_at or timezone.now()
        application.save()
        # Demo activation is explicit, idempotent, and uses the same canonical
        # professional-subscription boundary as reviewed applications. It never
        # fabricates Designer Pro payment or restarts a consumed Manufacturer trial.
        ensure_subscription_for_organization(
            org,
            activation_at=application.reviewed_at,
            actor=owner,
        )
        return org

    def _media(self, owner, key, filename):
        path = f"/static/demo/{filename}"
        media, _ = MediaAsset.objects.update_or_create(
            provider=MediaAsset.Provider.LOCAL_DEV,
            provider_asset_id=path,
            defaults={
                "original_filename": filename,
                "mime_type": "image/svg+xml",
                "size_bytes": 1,
                "access": MediaAsset.Access.PUBLIC,
                "metadata": {"demo": True, "static_url": path, "key": key},
                "uploaded_by": owner,
            },
        )
        return media

    def _design(self, org, owner, spec, media):
        design, _ = GarmentDesign.objects.get_or_create(
            organization=org,
            title=spec["title"],
            defaults={"created_by": owner},
        )
        design.description = spec["description"]
        design.category = spec["category"]
        design.status = GarmentDesign.Status.APPROVED
        design.full_clean()
        design.save()

        version, _ = GarmentDesignVersion.objects.get_or_create(
            design=design,
            version_number=1,
            defaults={"created_by": owner},
        )
        version.status = GarmentDesignVersion.Status.APPROVED
        version.summary = spec["summary"]
        version.base_material = spec["material"]
        version.construction_notes = spec["construction"]
        version.technical_specs = spec["technical"]
        version.submitted_at = version.submitted_at or timezone.now()
        version.reviewed_at = version.reviewed_at or timezone.now()
        version.review_notes = "Approved QA demo technical definition."
        version.full_clean()
        version.save()

        for order, (label, measurements) in enumerate(spec["sizes"]):
            SizeChartRow.objects.update_or_create(
                version=version,
                size_label=label,
                defaults={"measurements": measurements, "sort_order": order},
            )

        zones = {}
        for zone in spec["zones"]:
            obj, _ = DecorationZone.objects.update_or_create(
                version=version,
                name=zone["name"],
                defaults={
                    "method": zone["method"],
                    "placement": zone["placement"],
                    "max_width_mm": zone["width"],
                    "max_height_mm": zone["height"],
                    "notes": zone.get("notes", ""),
                },
            )
            obj.full_clean()
            zones[zone["name"]] = obj

        asset, _ = DesignAsset.objects.get_or_create(
            version=version,
            kind=DesignAsset.Kind.PRODUCT_IMAGE,
            media_asset=media,
            defaults={"label": f"{spec['title']} QA preview"},
        )
        asset.full_clean()
        return design, version, zones

    def _artwork(self, org, owner, spec, media):
        artwork, _ = Artwork.objects.get_or_create(
            organization=org,
            title=spec["title"],
            defaults={"created_by": owner},
        )
        artwork.description = spec["description"]
        artwork.tags = spec["tags"]
        artwork.status = Artwork.Status.APPROVED
        artwork.full_clean()
        artwork.save()
        version, _ = ArtworkVersion.objects.get_or_create(
            artwork=artwork,
            version_number=1,
            defaults={"created_by": owner},
        )
        version.status = ArtworkVersion.Status.APPROVED
        version.color_profile = "sRGB"
        version.production_notes = spec["production_notes"]
        version.metadata = spec["metadata"]
        version.submitted_at = version.submitted_at or timezone.now()
        version.reviewed_at = version.reviewed_at or timezone.now()
        version.full_clean()
        version.save()
        IPDeclaration.objects.update_or_create(
            version=version,
            defaults={
                "rights_basis": IPDeclaration.RightsBasis.ORIGINAL,
                "rights_holder_name": "FABINZI Demo Studio",
                "third_party_content": False,
                "details": "Original artwork created solely for FABINZI QA.",
                "accepts_ip_policy": True,
                "declared_by": owner,
            },
        )
        asset, _ = ArtworkAsset.objects.get_or_create(
            version=version,
            kind=ArtworkAsset.Kind.PREVIEW,
            media_asset=media,
            defaults={"label": f"{spec['title']} QA preview"},
        )
        asset.full_clean()
        return artwork, version

    def _designed_product(self, org, owner, *, garment_version, artwork_version, title, description, placement=None):
        product, _ = DesignedProduct.objects.get_or_create(
            organization=org,
            garment_version=garment_version,
            artwork_version=artwork_version,
            title=title,
            defaults={"created_by": owner},
        )
        product.description = description
        product.status = DesignedProduct.Status.PUBLISHED
        product.full_clean()
        product.save()
        if placement:
            row, _ = ArtworkPlacement.objects.update_or_create(
                product=product,
                decoration_zone=placement["zone"],
                defaults={"transform": placement["transform"], "production_method": placement["method"]},
            )
            row.full_clean()
            row.save()
        return product

    def _store_product(self, store, designed_product, *, slug, title_en, title_ar, price, customization, image, variants, featured=False):
        product, _ = StoreProduct.objects.get_or_create(
            storefront=store,
            slug=slug,
            defaults={"designed_product": designed_product, "title_en": title_en, "base_price": price},
        )
        product.designed_product = designed_product
        product.status = StoreProduct.Status.PUBLISHED
        product.title_en = title_en
        product.title_ar = title_ar
        product.description_en = f"QA demo {title_en} for FABINZI end-to-end testing."
        product.description_ar = f"منتج تجريبي لاختبار منصة FABINZI: {title_ar}."
        product.base_price = Decimal(str(price))
        product.currency = "EGP"
        product.fulfillment_mode = StoreProduct.FulfillmentMode.MADE_TO_ORDER
        product.lead_time_days = 7
        product.customization_enabled = customization
        product.featured = featured
        product.published_at = product.published_at or timezone.now()
        product.full_clean()
        product.save()
        image_row, _ = StoreProductImage.objects.get_or_create(product=product, media_asset=image)
        image_row.alt_en = title_en
        image_row.alt_ar = title_ar
        image_row.full_clean()
        image_row.save()
        result = []
        for item in variants:
            variant, _ = ProductVariant.objects.update_or_create(
                sku=item["sku"],
                defaults={
                    "product": product,
                    "size": item.get("size", ""),
                    "color_name": item.get("color", ""),
                    "color_hex": item.get("hex", ""),
                    "price_adjustment": Decimal(str(item.get("adjustment", 0))),
                    "stock_quantity": item.get("stock"),
                    "is_active": True,
                },
            )
            variant.full_clean()
            variant.save()
            result.append(variant)
        return product, result

    def _offer(self, designer_org, manufacturer_org, designer, manufacturer, designed_product, *, title, quantity, unit_price, methods, selected=False):
        rfq = RFQ.objects.filter(designer_organization=designer_org, designed_product=designed_product, title=title).first()
        if not rfq:
            rfq = RFQ.objects.create(
                designer_organization=designer_org,
                designed_product=designed_product,
                title=title,
                quantity=quantity,
                size_breakdown={"M": quantity // 2, "L": quantity - quantity // 2},
                color_requirements=["Black", "White"],
                requested_methods=methods,
                target_unit_price=Decimal(str(unit_price + 15)),
                currency="EGP",
                desired_delivery_date=(timezone.localdate() + timedelta(days=30)),
                delivery_country="EG",
                delivery_city="Cairo",
                notes="QA manufacturing opportunity generated by seed_demo.",
                status=RFQ.Status.OPEN,
                created_by=designer,
                opened_at=timezone.now(),
            )
        invitation, _ = RFQInvitation.objects.get_or_create(rfq=rfq, manufacturer=manufacturer_org)
        quote, created = ManufacturerQuote.objects.get_or_create(
            invitation=invitation,
            defaults={
                "status": ManufacturerQuote.Status.SUBMITTED,
                "unit_price": Decimal(str(unit_price)),
                "setup_fee": Decimal("250.00"),
                "sample_fee": Decimal("150.00"),
                "shipping_estimate": Decimal("500.00"),
                "currency": "EGP",
                "minimum_order_quantity": min(25, quantity),
                "production_lead_days": 12,
                "sample_lead_days": 3,
                "valid_until": timezone.localdate() + timedelta(days=30),
                "notes": "QA manufacturing offer.",
                "created_by": manufacturer,
                "submitted_at": timezone.now(),
            },
        )
        if created:
            invitation.status = RFQInvitation.Status.QUOTED
            invitation.responded_at = timezone.now()
            invitation.save(update_fields=["status", "responded_at"])
            rfq.status = RFQ.Status.QUOTED
            rfq.save(update_fields=["status", "updated_at"])
        if selected and not hasattr(rfq, "selection"):
            quote.status = ManufacturerQuote.Status.ACCEPTED
            quote.save(update_fields=["status", "updated_at"])
            ManufacturerSelection.objects.create(rfq=rfq, quote=quote, manufacturer=manufacturer_org, selected_by=designer)
            rfq.status = RFQ.Status.SELECTED
            rfq.selected_at = timezone.now()
            rfq.save(update_fields=["status", "selected_at", "updated_at"])
        return rfq, quote

    def _seed(self, passwords):
        admin = self._user("fabinzi_demo_admin", settings.DEMO_ADMIN_EMAIL, passwords["admin"], first_name="FABINZI", last_name="Admin", staff=True, superuser=True)
        designer = self._user("fabinzi_demo_designer", settings.DEMO_DESIGNER_EMAIL, passwords["designer"], first_name="Demo", last_name="Designer", language="ar", theme="light")
        manufacturer = self._user("fabinzi_demo_manufacturer", settings.DEMO_MANUFACTURER_EMAIL, passwords["manufacturer"], first_name="Demo", last_name="Manufacturer", language="en", theme="dark")
        customer = self._user("fabinzi_demo_customer", settings.DEMO_CUSTOMER_EMAIL, passwords["customer"], first_name="Demo", last_name="Customer", language="en", theme="dark")

        designer_org = self._organization(
            kind=Organization.Kind.DESIGNER,
            name="FABINZI Demo Studio",
            owner=designer,
            email=settings.DEMO_DESIGNER_EMAIL,
            city="New Cairo",
            address="90 North Street",
            website="https://example.com/fabinzi-demo-designer",
            phone="+201000000101",
        )
        DesignerProfile.objects.update_or_create(
            organization=designer_org,
            defaults={
                "studio_name": "FABINZI Demo Studio",
                "portfolio_url": "https://example.com/fabinzi-demo-designer/portfolio",
                "social_links": {"instagram": "@fabinzi_demo"},
                "legal_registration_number": "QA-DES-2026-001",
                "tax_number": "QA-TAX-DES-001",
                "payout_information": "QA only - no real payout credentials.",
                "terms_accepted": True,
                "terms_accepted_at": timezone.now(),
            },
        )

        manufacturer_org = self._organization(
            kind=Organization.Kind.MANUFACTURER,
            name="FABINZI Demo Manufacturing",
            owner=manufacturer,
            email=settings.DEMO_MANUFACTURER_EMAIL,
            city="10th of Ramadan City",
            address="Industrial Zone A, Plot QA-12",
            website="https://example.com/fabinzi-demo-manufacturer",
            phone="+201000000202",
        )
        ManufacturerProfile.objects.update_or_create(
            organization=manufacturer_org,
            defaults={
                "commercial_registration": "QA-MFR-2026-001",
                "tax_number": "QA-TAX-MFR-001",
                "google_maps_url": "https://maps.google.com/?q=30.3065,31.7415",
                "primary_contact_person": "QA Production Manager",
                "contact_job_title": "Production Manager",
                "whatsapp": "+201000000202",
                "manufacturing_categories": ["T-Shirts", "Dress", "Cap", "Bag"],
                "equipment": ["Cut & sew lines", "DTF", "DTG", "Embroidery"],
                "capability_summary": {"materials": ["cotton", "polyester", "canvas"], "gsm_range": [140, 320]},
                "daily_capacity": 600,
                "monthly_capacity": 15000,
                "certifications": ["QA-DEMO"],
                "payout_information": "QA only - no real payout credentials.",
                "terms_accepted": True,
                "terms_accepted_at": timezone.now(),
            },
        )

        garment_specs = [
            {"key":"bag","title":"Bag","title_ar":"حقيبة","category":"bag","description":"Durable canvas tote bag with reinforced handles.","summary":"Canvas tote suitable for print customization.","material":"320 GSM cotton canvas","construction":"Double-stitched seams and reinforced handles.","technical":{"gsm":320,"fabric":"cotton canvas","colors":["Natural","Black"],"required_capabilities":["cut_sew","print"]},"sizes":[("ONE",{"width_cm":38,"height_cm":42})],"zones":[{"name":"Front Print","method":"print","placement":{"x":0.5,"y":0.48},"width":260,"height":280}]},
            {"key":"cap","title":"Cap","title_ar":"كاب","category":"cap","description":"Six-panel cotton cap prepared for embroidery.","summary":"Structured cap for embroidery workflows.","material":"260 GSM cotton twill","construction":"Six-panel crown, curved visor and adjustable closure.","technical":{"gsm":260,"fabric":"cotton twill","colors":["Black","Navy","Beige"],"required_capabilities":["cut_sew","embroidery"]},"sizes":[("ADJ",{"head_circumference_cm":"54-62"})],"zones":[{"name":"Front Embroidery","method":"embroidery","placement":{"x":0.5,"y":0.42},"width":110,"height":55}]},
            {"key":"mens-tshirt","title":"Men's T-Shirt","title_ar":"تيشيرت رجالي","category":"tshirt_men","description":"Regular-fit men's crew neck T-shirt.","summary":"Core jersey T-shirt supporting plain and printed purchases.","material":"180 GSM combed cotton jersey","construction":"Crew neck rib, shoulder tape and double-needle hems.","technical":{"gsm":180,"fabric":"combed cotton jersey","colors":["Black","White","Navy"],"required_capabilities":["cut_sew","print"],"print_methods":["DTF","DTG"]},"sizes":[("S",{"chest_cm":50,"length_cm":69}),("M",{"chest_cm":53,"length_cm":72}),("L",{"chest_cm":56,"length_cm":74}),("XL",{"chest_cm":59,"length_cm":76})],"zones":[{"name":"Front Chest","method":"print","placement":{"x":0.5,"y":0.38},"width":300,"height":380},{"name":"Back","method":"print","placement":{"x":0.5,"y":0.42},"width":320,"height":420}]},
            {"key":"womens-tshirt","title":"Women's T-Shirt","title_ar":"تيشيرت حريمي","category":"tshirt_women","description":"Women's fitted crew neck T-shirt.","summary":"Soft jersey T-shirt supporting customer customization.","material":"170 GSM cotton-elastane jersey","construction":"Fitted body, bound neck and double-needle hems.","technical":{"gsm":170,"fabric":"cotton elastane jersey","colors":["White","Black","Rose"],"required_capabilities":["cut_sew","print"],"print_methods":["DTF","DTG"]},"sizes":[("S",{"chest_cm":44,"length_cm":61}),("M",{"chest_cm":47,"length_cm":63}),("L",{"chest_cm":50,"length_cm":65})],"zones":[{"name":"Front Chest","method":"print","placement":{"x":0.5,"y":0.38},"width":270,"height":340}]},
            {"key":"dress","title":"Dress","title_ar":"فستان","category":"dress","description":"Simple woven day dress for plain purchase QA.","summary":"Lightweight day dress with controlled non-customized storefront configuration.","material":"150 GSM viscose blend","construction":"Panelled body, concealed back zip and finished hem.","technical":{"gsm":150,"fabric":"viscose blend","colors":["Black","Sand","Olive"],"required_capabilities":["cut_sew","finishing"]},"sizes":[("S",{"bust_cm":88,"waist_cm":72,"length_cm":112}),("M",{"bust_cm":94,"waist_cm":78,"length_cm":114}),("L",{"bust_cm":100,"waist_cm":84,"length_cm":116})],"zones":[]},
        ]

        design_media = {spec["key"]: self._media(designer, spec["key"], f"garment-{spec['key']}.svg") for spec in garment_specs}
        designs = {}
        for spec in garment_specs:
            _, version, zones = self._design(designer_org, designer, spec, design_media[spec["key"]])
            designs[spec["key"]] = {"version": version, "zones": zones, "spec": spec}

        artwork_specs = [
            {"key":"blank","title":"Blank Base","description":"Intentional no-placement artwork record used to model plain QA products in the current product schema.","tags":["plain","qa"],"production_notes":"No decoration placement. Used for plain garment QA.","metadata":{"suitable_for_print":False,"suitable_for_embroidery":False,"royalty_percent":0}},
            {"key":"cairo-lines","title":"Cairo Lines","description":"Original geometric line artwork inspired by urban rhythm.","tags":["geometric","cairo","print"],"production_notes":"Optimized for DTF/DTG printing.","metadata":{"suitable_for_print":True,"suitable_for_embroidery":False,"royalty_percent":8}},
            {"key":"needle-star","title":"Needle Star","description":"Original compact star motif for embroidery QA.","tags":["star","embroidery","minimal"],"production_notes":"Compact embroidery-friendly motif.","metadata":{"suitable_for_print":True,"suitable_for_embroidery":True,"royalty_percent":6}},
        ]
        artworks = {}
        for spec in artwork_specs:
            media = self._media(designer, spec["key"], f"artwork-{spec['key']}.svg")
            _, version = self._artwork(designer_org, designer, spec, media)
            artworks[spec["key"]] = {"version": version, "media": media}

        # Preserve the accepted five-design/three-artwork QA graph without
        # pretending the Designer paid for Pro. Starter entitlement accounting
        # retains two active slots of each type and plan-pauses the excess only
        # in entitlement state; canonical technical-review statuses stay intact.
        overlay_now = timezone.now()
        for index, row in enumerate(designs.values()):
            paused = index >= 2
            DesignPlanEntitlementState.objects.update_or_create(
                design=row["version"].design,
                defaults={
                    "plan_paused": paused,
                    "retained": not paused,
                    "protected_active_chain": False,
                    "pause_reason": "demo_seed_starter_overlay" if paused else "",
                    "paused_at": overlay_now if paused else None,
                },
            )
        for index, row in enumerate(artworks.values()):
            paused = index >= 2
            ArtworkPlanEntitlementState.objects.update_or_create(
                artwork=row["version"].artwork,
                defaults={
                    "plan_paused": paused,
                    "retained": not paused,
                    "protected_active_chain": False,
                    "pause_reason": "demo_seed_starter_overlay" if paused else "",
                    "paused_at": overlay_now if paused else None,
                },
            )

        base_products = {}
        for key, row in designs.items():
            base_products[key] = self._designed_product(
                designer_org,
                designer,
                garment_version=row["version"],
                artwork_version=artworks["blank"]["version"],
                title=f"{row['spec']['title']} Plain",
                description="Plain QA configuration with no artwork placement.",
            )

        ready_product = self._designed_product(
            designer_org,
            designer,
            garment_version=designs["mens-tshirt"]["version"],
            artwork_version=artworks["cairo-lines"]["version"],
            title="Cairo Lines Men's T-Shirt",
            description="Ready Designed Product combining the approved Men's T-Shirt with Cairo Lines artwork.",
            placement={"zone":designs["mens-tshirt"]["zones"]["Front Chest"],"transform":{"x":0.09,"y":0.01,"width":0.82,"height":0.82,"rotation":0},"method":"print"},
        )

        store, _ = Storefront.objects.get_or_create(
            organization=designer_org,
            defaults={"slug":"fabinzi-demo-studio","name_en":"FABINZI Demo Studio"},
        )
        store.slug = "fabinzi-demo-studio"
        store.name_en = "FABINZI Demo Studio"
        store.name_ar = "استوديو فابينزي التجريبي"
        store.about_en = "QA storefront for testing the complete FABINZI customer journey."
        store.about_ar = "متجر تجريبي لاختبار رحلة العميل الكاملة على منصة فابينزي."
        store.status = Storefront.Status.PUBLISHED
        store.published_at = store.published_at or timezone.now()
        store.full_clean()
        store.save()

        catalog = {}
        catalog["mens-tshirt"], mens_variants = self._store_product(store, base_products["mens-tshirt"], slug="mens-tshirt-plain", title_en="Men's T-Shirt - Plain", title_ar="تيشيرت رجالي سادة", price=349, customization=True, image=design_media["mens-tshirt"], featured=True, variants=[{"sku":"QA-MTS-M-BLK","size":"M","color":"Black","hex":"#111111"},{"sku":"QA-MTS-L-WHT","size":"L","color":"White","hex":"#FFFFFF"}])
        catalog["womens-tshirt"], womens_variants = self._store_product(store, base_products["womens-tshirt"], slug="womens-tshirt-plain", title_en="Women's T-Shirt - Customizable", title_ar="تيشيرت حريمي قابل للتخصيص", price=329, customization=True, image=design_media["womens-tshirt"], variants=[{"sku":"QA-WTS-M-WHT","size":"M","color":"White","hex":"#FFFFFF"},{"sku":"QA-WTS-L-BLK","size":"L","color":"Black","hex":"#111111"}])
        catalog["cap"], cap_variants = self._store_product(store, base_products["cap"], slug="cap-plain", title_en="Cap - Embroidery Ready", title_ar="كاب جاهز للتطريز", price=279, customization=True, image=design_media["cap"], variants=[{"sku":"QA-CAP-ADJ-NVY","size":"ADJ","color":"Navy","hex":"#1E2A44"}])
        catalog["bag"], bag_variants = self._store_product(store, base_products["bag"], slug="bag-plain", title_en="Canvas Bag - Printable", title_ar="حقيبة كانفاس قابلة للطباعة", price=299, customization=True, image=design_media["bag"], variants=[{"sku":"QA-BAG-ONE-NAT","size":"ONE","color":"Natural","hex":"#D8C8A8"}])
        catalog["dress"], dress_variants = self._store_product(store, base_products["dress"], slug="dress-plain", title_en="Day Dress - Plain", title_ar="فستان يومي سادة", price=899, customization=False, image=design_media["dress"], variants=[{"sku":"QA-DRS-M-BLK","size":"M","color":"Black","hex":"#111111"}])
        catalog["ready"], ready_variants = self._store_product(store, ready_product, slug="cairo-lines-tee", title_en="Cairo Lines Ready T-Shirt", title_ar="تيشيرت كايرو لاينز جاهز", price=449, customization=False, image=artworks["cairo-lines"]["media"], featured=True, variants=[{"sku":"QA-READY-M-WHT","size":"M","color":"White","hex":"#FFFFFF"}])

        listing, _ = ManufacturerListing.objects.get_or_create(organization=manufacturer_org)
        listing.status = ManufacturerListing.Status.PUBLISHED
        listing.headline_en = "Flexible cut-sew, DTF, DTG and embroidery manufacturing"
        listing.headline_ar = "تصنيع مرن وقص وخياطة وطباعة وتطريز"
        listing.overview_en = "QA manufacturer covering the demo garments and decoration methods."
        listing.overview_ar = "مصنع تجريبي يغطي منتجات وطرق تنفيذ بيئة الاختبار."
        listing.public_email = settings.DEMO_MANUFACTURER_EMAIL
        listing.public_phone = "+201000000202"
        listing.accepts_rfq = True
        listing.sample_orders = True
        listing.min_order_quantity = 25
        listing.lead_time_min_days = 7
        listing.lead_time_max_days = 18
        listing.available_monthly_capacity = 15000
        listing.materials = ["cotton jersey 170-220 GSM", "cotton twill", "canvas 280-340 GSM", "viscose blends"]
        listing.production_methods = ["cut_sew", "DTF", "DTG", "embroidery", "finishing", "packaging"]
        listing.markets = ["Egypt", "MENA"]
        listing.certifications = ["QA-DEMO"]
        listing.last_capacity_update = timezone.now()
        listing.published_at = listing.published_at or timezone.now()
        listing.full_clean()
        listing.save()

        capability_rows = [
            (ManufacturerCapability.CapabilityType.CUT_SEW, "Garments & Bags", ["T-Shirts", "Dress", "Bag"]),
            (ManufacturerCapability.CapabilityType.PRINT, "DTF / DTG Printing", ["DTF", "DTG"]),
            (ManufacturerCapability.CapabilityType.EMBROIDERY, "Cap & Garment Embroidery", ["computerized embroidery"]),
            (ManufacturerCapability.CapabilityType.FINISHING, "Garment Finishing", ["pressing", "thread trimming"]),
            (ManufacturerCapability.CapabilityType.PACKAGING, "Retail Packaging", ["folding", "bagging", "labeling"]),
        ]
        for capability_type, name, methods in capability_rows:
            cap, _ = ManufacturerCapability.objects.update_or_create(
                listing=listing,
                capability_type=capability_type,
                name=name,
                defaults={"description":"QA capability for FABINZI demo workflows.","methods":methods,"min_quantity":25,"max_quantity":5000,"lead_time_days":12,"is_active":True},
            )
            cap.full_clean()
            cap.save()

        self._offer(designer_org, manufacturer_org, designer, manufacturer, base_products["mens-tshirt"], title="QA Men's T-Shirt Production", quantity=100, unit_price=155, methods=["cut_sew","DTF","DTG"], selected=True)
        self._offer(designer_org, manufacturer_org, designer, manufacturer, base_products["cap"], title="QA Cap Embroidery Production", quantity=80, unit_price=120, methods=["cut_sew","embroidery"])
        self._offer(designer_org, manufacturer_org, designer, manufacturer, base_products["bag"], title="QA Canvas Bag Printing Production", quantity=120, unit_price=135, methods=["cut_sew","DTF"])

        cod, _ = IntegrationConfig.objects.get_or_create(provider=IntegrationConfig.Provider.COD)
        if not cod.enabled:
            cod.enabled = True
            cod.save(update_fields=["enabled", "updated_at"])

        plain_project = StudioProject.objects.filter(customer=customer, customer_notes="FABINZI_DEMO_READY_PLAIN").first()
        if not plain_project:
            plain_project = StudioProject.objects.create(customer=customer, product=catalog["mens-tshirt"], variant=mens_variants[0], status=StudioProject.Status.READY, quantity=1, customer_notes="FABINZI_DEMO_READY_PLAIN", ready_at=timezone.now())
        CheckoutSession.objects.get_or_create(
            studio_project=plain_project,
            defaults={
                "customer":customer,
                "shipping_name":"Demo Customer",
                "shipping_phone":"+201000000303",
                "shipping_email":settings.DEMO_CUSTOMER_EMAIL,
                "shipping_address1":"QA Delivery Address, New Cairo",
                "shipping_city":"Cairo",
                "shipping_region":"Cairo",
                "shipping_country":"EG",
                "postal_code":"11835",
                "subtotal":plain_project.variant.price,
                "total":plain_project.variant.price,
                "currency":"EGP",
            },
        )

        custom_project = StudioProject.objects.filter(customer=customer, customer_notes="FABINZI_DEMO_CUSTOMIZABLE_PROJECT").first()
        if not custom_project:
            custom_project = StudioProject.objects.create(customer=customer, product=catalog["womens-tshirt"], variant=womens_variants[0], status=StudioProject.Status.DRAFT, quantity=1, customer_notes="FABINZI_DEMO_CUSTOMIZABLE_PROJECT")
        customization, _ = CustomerCustomization.objects.get_or_create(project=custom_project, defaults={"enabled":True})
        zone = designs["womens-tshirt"]["zones"]["Front Chest"]
        element, _ = CustomizationElement.objects.get_or_create(customization=customization, decoration_zone=zone, kind=CustomizationElement.Kind.TEXT, text="FABINZI QA")
        element.transform = {"x":0.5,"y":0.45,"scale":1.0,"rotation":0}
        element.style = {"font":"sans-serif","size":32}
        element.full_clean()
        element.save()

        ready_project = StudioProject.objects.filter(customer=customer, customer_notes="FABINZI_DEMO_READY_DESIGNED").first()
        if not ready_project:
            StudioProject.objects.create(customer=customer, product=catalog["ready"], variant=ready_variants[0], status=StudioProject.Status.READY, quantity=1, customer_notes="FABINZI_DEMO_READY_DESIGNED", ready_at=timezone.now())

        return {"admin":admin,"designer":designer,"manufacturer":manufacturer,"customer":customer}
