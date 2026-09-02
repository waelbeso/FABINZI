from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organizations", "0004_v2_application_review_target_and_public_revision_states"),
        ("media", "0002_rename_media_asset_index"),
        ("manufacturer_marketplace", "0001_initial"),
        ("storefront", "0002_visual_studio_elements"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProfessionalPublicState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slug", models.SlugField(max_length=220, unique=True)),
                ("visibility", models.CharField(choices=[("hidden", "Hidden"), ("pending_approval", "Pending FABINZI approval"), ("visible", "Visible")], db_index=True, default="hidden", max_length=24)),
                ("public_name_en", models.CharField(blank=True, max_length=180)),
                ("public_name_ar", models.CharField(blank=True, max_length=180)),
                ("bio_en", models.TextField(blank=True)),
                ("bio_ar", models.TextField(blank=True)),
                ("specializations", models.JSONField(blank=True, default=list)),
                ("public_google_maps_url", models.URLField(blank=True, max_length=500)),
                ("public_categories", models.JSONField(blank=True, default=list)),
                ("public_certifications", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("cover_image", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="public_profile_cover_uses", to="media.mediaasset")),
                ("organization", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="public_state", to="organizations.organization")),
                ("profile_image", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="public_profile_primary_uses", to="media.mediaasset")),
            ],
        ),
        migrations.CreateModel(
            name="ManufacturerCapabilityVerification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("canonical_code", models.CharField(choices=[("garment_manufacturing", "Garment Manufacturing"), ("dtf", "DTF"), ("dtg", "DTG"), ("embroidery", "Embroidery")], max_length=32)),
                ("status", models.CharField(choices=[("verified", "Verified"), ("revoked", "Revoked")], db_index=True, default="verified", max_length=16)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("capability", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="public_verification", to="manufacturer_marketplace.manufacturercapability")),
                ("verified_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="verified_public_manufacturer_capabilities", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="ManufacturerPublicProductApproval",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("approved", "Approved"), ("revoked", "Revoked")], db_index=True, default="approved", max_length=16)),
                ("is_visible", models.BooleanField(default=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approved_manufacturer_public_products", to=settings.AUTH_USER_MODEL)),
                ("manufacturer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="public_product_approvals", to="organizations.organization")),
                ("store_product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="manufacturer_public_approvals", to="storefront.storeproduct")),
            ],
        ),
        migrations.AddIndex(model_name="professionalpublicstate", index=models.Index(fields=["visibility", "organization"], name="pubprof_visibility_org_idx")),
        migrations.AddConstraint(model_name="manufacturerpublicproductapproval", constraint=models.UniqueConstraint(fields=("manufacturer", "store_product"), name="uniq_public_manufacturer_store_product")),
        migrations.AddIndex(model_name="manufacturerpublicproductapproval", index=models.Index(fields=["manufacturer", "status", "is_visible"], name="pubprod_mfr_status_idx")),
    ]
