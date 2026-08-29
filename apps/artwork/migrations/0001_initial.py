from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organizations", "0002_align_index_names"),
        ("media", "0002_rename_media_asset_index"),
        ("design", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(name="Artwork", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("title", models.CharField(max_length=220)), ("description", models.TextField(blank=True)), ("tags", models.JSONField(blank=True, default=list)),
            ("status", models.CharField(choices=[("draft","Draft"),("in_review","In review"),("revision_required","Revision required"),("approved","Approved"),("rejected","Rejected"),("suspended","Suspended"),("archived","Archived")], db_index=True, default="draft", max_length=24)),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_artworks", to=settings.AUTH_USER_MODEL)),
            ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="artworks", to="organizations.organization")),
        ], options={"ordering": ("-updated_at",), "indexes": [models.Index(fields=["organization","status"], name="artwork_org_status_idx")]}),
        migrations.CreateModel(name="ArtworkVersion", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("version_number", models.PositiveIntegerField()),
            ("status", models.CharField(choices=[("draft","Draft"),("submitted","Submitted"),("revision_required","Revision required"),("approved","Approved"),("rejected","Rejected")], db_index=True, default="draft", max_length=24)),
            ("color_profile", models.CharField(blank=True, max_length=80)), ("production_notes", models.TextField(blank=True)), ("metadata", models.JSONField(blank=True, default=dict)),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("submitted_at", models.DateTimeField(blank=True, null=True)), ("reviewed_at", models.DateTimeField(blank=True, null=True)), ("review_notes", models.TextField(blank=True)),
            ("artwork", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="versions", to="artwork.artwork")),
            ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_artwork_versions", to=settings.AUTH_USER_MODEL)),
            ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_artwork_versions", to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ("-version_number",)}),
        migrations.AddConstraint(model_name="artworkversion", constraint=models.UniqueConstraint(fields=("artwork","version_number"), name="unique_artwork_version_number")),
        migrations.CreateModel(name="ArtworkAsset", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("kind", models.CharField(choices=[("preview","Preview image"),("source","Production source"),("rights_evidence","Rights evidence")], max_length=24)),
            ("label", models.CharField(blank=True, max_length=180)), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("media_asset", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="artwork_assets", to="media.mediaasset")),
            ("version", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assets", to="artwork.artworkversion")),
        ]),
        migrations.CreateModel(name="IPDeclaration", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("rights_basis", models.CharField(choices=[("original","Original work owned by creator"),("exclusive_license","Exclusive license"),("nonexclusive_license","Non-exclusive license"),("public_domain","Public domain"),("other","Other documented rights")], max_length=32)),
            ("rights_holder_name", models.CharField(max_length=220)), ("third_party_content", models.BooleanField(default=False)), ("details", models.TextField(blank=True)), ("accepts_ip_policy", models.BooleanField(default=False)), ("declared_at", models.DateTimeField(auto_now_add=True)),
            ("declared_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ip_declarations", to=settings.AUTH_USER_MODEL)),
            ("version", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="ip_declaration", to="artwork.artworkversion")),
        ]),
        migrations.CreateModel(name="ArtworkReview", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("decision", models.CharField(choices=[("approved","Approved"),("revision_required","Revision required"),("rejected","Rejected")], max_length=24)), ("notes", models.TextField(blank=True)), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("reviewer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="artwork_reviews", to=settings.AUTH_USER_MODEL)),
            ("version", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reviews", to="artwork.artworkversion")),
        ], options={"ordering": ("-created_at",)}),
        migrations.CreateModel(name="DesignedProduct", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("title", models.CharField(max_length=220)), ("description", models.TextField(blank=True)),
            ("status", models.CharField(choices=[("draft","Draft"),("published","Published"),("suspended","Suspended"),("archived","Archived")], db_index=True, default="draft", max_length=20)),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("artwork_version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="designed_products", to="artwork.artworkversion")),
            ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_designed_products", to=settings.AUTH_USER_MODEL)),
            ("garment_version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="designed_products", to="design.garmentdesignversion")),
            ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="designed_products", to="organizations.organization")),
        ], options={"ordering": ("-updated_at",), "indexes": [models.Index(fields=["organization","status"], name="dproduct_org_status_idx")]}),
        migrations.CreateModel(name="ArtworkPlacement", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("transform", models.JSONField(default=dict, help_text="Normalized x/y/scale/rotation transform.")),
            ("production_method", models.CharField(choices=[("print","Print"),("embroidery","Embroidery")], max_length=20)),
            ("decoration_zone", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="artwork_placements", to="design.decorationzone")),
            ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="placements", to="artwork.designedproduct")),
        ]),
        migrations.AddConstraint(model_name="artworkplacement", constraint=models.UniqueConstraint(fields=("product","decoration_zone"), name="unique_product_decoration_zone")),
        migrations.CreateModel(name="IPCase", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("reporter_name", models.CharField(max_length=220)), ("reporter_email", models.EmailField(max_length=254)),
            ("claimant_rights", models.TextField()), ("allegation", models.TextField()),
            ("status", models.CharField(choices=[("open","Open"),("under_review","Under review"),("action_required","Action required"),("resolved","Resolved"),("dismissed","Dismissed")], db_index=True, default="open", max_length=24)),
            ("resolution", models.CharField(choices=[("none","No resolution yet"),("takedown","Takedown"),("restored","Restored"),("claim_rejected","Claim rejected")], default="none", max_length=24)),
            ("staff_notes", models.TextField(blank=True)), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)), ("resolved_at", models.DateTimeField(blank=True, null=True)),
            ("artwork", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="ip_cases", to="artwork.artwork")),
            ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_ip_cases", to=settings.AUTH_USER_MODEL)),
            ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reported_ip_cases", to=settings.AUTH_USER_MODEL)),
            ("designed_product", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="ip_cases", to="artwork.designedproduct")),
        ], options={"ordering": ("-created_at",)}),
        migrations.CreateModel(name="IPCaseEvidence", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("description", models.CharField(blank=True, max_length=255)), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("case", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="evidence", to="artwork.ipcase")),
            ("media_asset", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ip_case_evidence", to="media.mediaasset")),
            ("submitted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
        ]),
    ]
