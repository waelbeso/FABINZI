# Generated for FABINZI Stage 1
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [("media", "0001_initial"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(name="Organization", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("kind", models.CharField(choices=[("designer", "Designer"), ("manufacturer", "Manufacturer")], db_index=True, max_length=20)),
            ("display_name", models.CharField(max_length=180)), ("legal_name", models.CharField(blank=True, max_length=220)),
            ("email", models.EmailField(max_length=254)), ("phone", models.CharField(blank=True, max_length=50)), ("website", models.URLField(blank=True)),
            ("address_line1", models.CharField(blank=True, max_length=255)), ("address_line2", models.CharField(blank=True, max_length=255)),
            ("city", models.CharField(blank=True, max_length=120)), ("region", models.CharField(blank=True, max_length=120)), ("country", models.CharField(default="EG", max_length=2)),
            ("verification_status", models.CharField(choices=[("draft", "Draft"), ("pending", "Pending verification"), ("active", "Active"), ("rejected", "Rejected"), ("suspended", "Suspended")], db_index=True, default="draft", max_length=20)),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_organizations", to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ("display_name",)}),
        migrations.CreateModel(name="DesignerProfile", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("studio_name", models.CharField(blank=True, max_length=180)), ("portfolio_url", models.URLField(blank=True)), ("social_links", models.JSONField(blank=True, default=dict)),
            ("legal_registration_number", models.CharField(blank=True, max_length=120)), ("tax_number", models.CharField(blank=True, max_length=120)),
            ("payout_information", models.TextField(blank=True, help_text="Stage 1 onboarding information only; payout execution is implemented in the finance stage.")),
            ("terms_accepted", models.BooleanField(default=False)), ("terms_accepted_at", models.DateTimeField(blank=True, null=True)),
            ("organization", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="designer_profile", to="organizations.organization")),
        ]),
        migrations.CreateModel(name="ManufacturerProfile", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("commercial_registration", models.CharField(blank=True, max_length=120)), ("tax_number", models.CharField(blank=True, max_length=120)),
            ("google_maps_url", models.URLField(blank=True)), ("primary_contact_person", models.CharField(blank=True, max_length=180)), ("contact_job_title", models.CharField(blank=True, max_length=120)),
            ("whatsapp", models.CharField(blank=True, max_length=50)), ("manufacturing_categories", models.JSONField(blank=True, default=list)), ("equipment", models.JSONField(blank=True, default=list)),
            ("capability_summary", models.JSONField(blank=True, default=dict)), ("daily_capacity", models.PositiveIntegerField(blank=True, null=True)), ("monthly_capacity", models.PositiveIntegerField(blank=True, null=True)),
            ("certifications", models.JSONField(blank=True, default=list)), ("payout_information", models.TextField(blank=True, help_text="Stage 1 onboarding information only; payout execution is implemented in the finance stage.")),
            ("terms_accepted", models.BooleanField(default=False)), ("terms_accepted_at", models.DateTimeField(blank=True, null=True)),
            ("organization", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="manufacturer_profile", to="organizations.organization")),
        ]),
        migrations.CreateModel(name="OnboardingApplication", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("status", models.CharField(choices=[("draft", "Draft"), ("submitted", "Submitted"), ("revision_required", "Revision required"), ("approved", "Approved"), ("rejected", "Rejected")], db_index=True, default="draft", max_length=24)),
            ("review_notes", models.TextField(blank=True)), ("revision_count", models.PositiveIntegerField(default=0)), ("submitted_at", models.DateTimeField(blank=True, null=True)),
            ("reviewed_at", models.DateTimeField(blank=True, null=True)), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("organization", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="onboarding_application", to="organizations.organization")),
            ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_onboarding_applications", to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ("-updated_at",)}),
        migrations.CreateModel(name="Membership", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("role", models.CharField(choices=[("owner", "Owner"), ("manager", "Manager"), ("designer", "Designer"), ("design_manager", "Design Manager"), ("accountant", "Accountant"), ("production_manager", "Production Manager"), ("operator", "Operator"), ("qc", "QC")], max_length=32)),
            ("is_active", models.BooleanField(default=True)), ("joined_at", models.DateTimeField(auto_now_add=True)),
            ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="organizations.organization")),
            ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="business_memberships", to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.CreateModel(name="VerificationDocument", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("document_type", models.CharField(choices=[("registration", "Registration document"), ("tax", "Tax document"), ("identity", "Identity / authorized representative"), ("certification", "Certification"), ("other", "Other")], max_length=32)),
            ("description", models.CharField(blank=True, max_length=255)), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("application", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="verification_documents", to="organizations.onboardingapplication")),
            ("media_asset", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="verification_documents", to="media.mediaasset")),
        ], options={"ordering": ("created_at",)}),
        migrations.AddConstraint(model_name="membership", constraint=models.UniqueConstraint(fields=("organization", "user"), name="unique_org_user_membership")),
        migrations.AddIndex(model_name="organization", index=models.Index(fields=["kind", "verification_status"], name="organizatio_kind_f69db6_idx")),
        migrations.AddIndex(model_name="membership", index=models.Index(fields=["user", "is_active"], name="organizatio_user_id_c945bc_idx")),
        migrations.AddIndex(model_name="membership", index=models.Index(fields=["organization", "role"], name="organizatio_organiz_76ec4d_idx")),
        migrations.AddIndex(model_name="onboardingapplication", index=models.Index(fields=["status", "updated_at"], name="organizatio_status_3ea338_idx")),
    ]
