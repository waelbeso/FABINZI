from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("artwork", "0001_initial"),
        ("design", "0002_v2_creator_technical_schema"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(model_name="artwork", name="symbolic_ref", field=models.CharField(blank=True, max_length=100, null=True, unique=True)),
        migrations.AddField(model_name="artworkversion", name="symbolic_ref", field=models.CharField(blank=True, max_length=120, null=True, unique=True)),
        migrations.AddField(model_name="artworkversion", name="intended_methods", field=models.JSONField(blank=True, default=list)),
        migrations.AddField(
            model_name="artworkversion",
            name="technical_check_status",
            field=models.CharField(choices=[("not_checked", "Not checked"), ("pass", "Pass"), ("fail", "Fail"), ("needs_evidence", "Needs evidence")], db_index=True, default="not_checked", max_length=24),
        ),
        migrations.AddField(model_name="artworkversion", name="technical_check_result", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="artworkversion", name="resolution_evidence", field=models.JSONField(blank=True, default=dict, help_text="Measured source-resolution/DPI evidence where genuinely available.")),
        migrations.AddField(model_name="artworkversion", name="embroidery_suitability_evidence", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="artworkasset", name="technical_role", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="designedproduct", name="symbolic_ref", field=models.CharField(blank=True, max_length=120, null=True, unique=True)),
        migrations.AddField(model_name="designedproduct", name="economic_attribution", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="designedproduct", name="reference_only", field=models.BooleanField(default=False)),
        migrations.AddField(
            model_name="designedproduct",
            name="garment_creator_organization",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="garment_attributed_designed_products", to="organizations.organization"),
        ),
        migrations.AddField(
            model_name="designedproduct",
            name="artwork_creator_organization",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="artwork_attributed_designed_products", to="organizations.organization"),
        ),
        migrations.AlterField(
            model_name="artworkplacement",
            name="production_method",
            field=models.CharField(choices=[("print", "Print (legacy)"), ("dtf", "DTF"), ("dtg", "DTG"), ("embroidery", "Embroidery")], max_length=20),
        ),
        migrations.CreateModel(
            name="ArtworkRegistrationSource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_name", models.CharField(max_length=220)),
                ("source_kind", models.CharField(default="external_procedure_source", max_length=80)),
                ("source_filename", models.CharField(blank=True, max_length=255)),
                ("source_sha256", models.CharField(blank=True, max_length=64)),
                ("source_version", models.CharField(blank=True, max_length=80)),
                ("source_date", models.DateField(blank=True, null=True)),
                ("scope_description", models.TextField(blank=True)),
                ("visual_graphic_applicability_confirmed", models.BooleanField(default=False)),
                ("field_schema", models.JSONField(blank=True, default=dict)),
                ("procedure_facts", models.JSONField(blank=True, default=dict)),
                ("source_limitations", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.AddConstraint(model_name="artworkregistrationsource", constraint=models.UniqueConstraint(fields=("source_name", "source_sha256", "source_version"), name="unique_artwork_registration_source_snapshot")),
        migrations.CreateModel(
            name="ArtworkRegistrationCase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("procedure_template_key", models.CharField(blank=True, max_length=100)),
                ("captured_data", models.JSONField(blank=True, default=dict)),
                ("representation_state", models.JSONField(blank=True, default=dict)),
                ("service_price_egp", models.DecimalField(decimal_places=2, default=Decimal("400.00"), max_digits=10)),
                ("official_fee_information", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("evidence_required", "Evidence required"), ("staff_review", "Staff review"), ("ready_external", "Ready for external submission"), ("submitted_external", "Submitted externally"), ("completed", "Completed"), ("rejected", "Rejected"), ("cancelled", "Cancelled")], db_index=True, default="draft", max_length=32)),
                ("source_applicability_confirmed_for_case", models.BooleanField(default=False)),
                ("external_reference", models.CharField(blank=True, max_length=180)),
                ("external_submitted_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("staff_notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("applicant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="artwork_registration_cases", to=settings.AUTH_USER_MODEL)),
                ("artwork_version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="registration_cases", to="artwork.artworkversion")),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_artwork_registration_cases", to=settings.AUTH_USER_MODEL)),
                ("source_snapshot", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="registration_cases", to="artwork.artworkregistrationsource")),
            ],
            options={"ordering": ("-updated_at",)},
        ),
        migrations.CreateModel(
            name="ArtworkRegistrationDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(max_length=100)),
                ("description", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("case", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="documents", to="artwork.artworkregistrationcase")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="artwork_registration_documents", to=settings.AUTH_USER_MODEL)),
                ("media_asset", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="artwork_registration_documents", to="media.mediaasset")),
            ],
        ),
    ]
