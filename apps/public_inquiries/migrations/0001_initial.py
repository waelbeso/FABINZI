import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organizations", "0004_v2_application_review_target_and_public_revision_states"),
        ("design", "0002_v2_creator_technical_schema"),
        ("artwork", "0003_align_v2_4_placement_transform"),
        ("media", "0002_rename_media_asset_index"),
        ("public_profiles", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PublicInquiryEmailChallenge",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reference", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("email", models.EmailField(db_index=True, max_length=254)),
                ("session_key_hash", models.CharField(max_length=64)),
                ("otp_hash", models.CharField(max_length=256)),
                ("expires_at", models.DateTimeField()),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="PublicInquiry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reference", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("target_kind", models.CharField(choices=[("designer", "Designer"), ("manufacturer", "Manufacturer")], max_length=16)),
                ("sender_email", models.EmailField(blank=True, max_length=254)),
                ("sender_email_verified", models.BooleanField(default=False)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("submitted", "Submitted"), ("handling", "Handling"), ("responded", "Responded"), ("closed", "Closed"), ("spam", "Spam / abuse")], db_index=True, default="draft", max_length=16)),
                ("designer_work_kind", models.CharField(blank=True, choices=[("garment_design", "Garment Design"), ("artwork", "Artwork"), ("ready_product", "Ready Designed Product")], max_length=24)),
                ("quantity", models.PositiveIntegerField(default=1)),
                ("size_requirements", models.JSONField(blank=True, default=dict)),
                ("color_requirements", models.JSONField(blank=True, default=list)),
                ("customization_description", models.TextField(blank=True)),
                ("delivery_city", models.CharField(blank=True, max_length=120)),
                ("delivery_country", models.CharField(blank=True, max_length=2)),
                ("desired_date", models.DateField(blank=True, null=True)),
                ("requirements", models.TextField(blank=True)),
                ("notes", models.TextField(blank=True)),
                ("staff_notes", models.TextField(blank=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("artwork", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="public_inquiries", to="artwork.artwork")),
                ("garment_design", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="public_inquiries", to="design.garmentdesign")),
                ("handled_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="public_inquiries_handled", to=settings.AUTH_USER_MODEL)),
                ("manufacturer_product_approval", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="public_inquiries", to="public_profiles.manufacturerpublicproductapproval")),
                ("ready_product", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="public_inquiries", to="artwork.designedproduct")),
                ("sender_user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="public_inquiries_sent", to=settings.AUTH_USER_MODEL)),
                ("target_organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="public_inquiries_received", to="organizations.organization")),
            ],
        ),
        migrations.CreateModel(
            name="PublicInquiryAttachment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("inquiry", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="attachments", to="public_inquiries.publicinquiry")),
                ("media_asset", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="public_inquiry_attachments", to="media.mediaasset")),
                ("uploaded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="public_inquiry_attachments", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="PublicInquiryMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sender_role", models.CharField(choices=[("visitor", "Visitor / customer"), ("professional", "Professional"), ("staff", "FABINZI staff")], max_length=16)),
                ("body", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="public_inquiry_messages", to=settings.AUTH_USER_MODEL)),
                ("inquiry", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="messages", to="public_inquiries.publicinquiry")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.AddIndex(model_name="publicinquiryemailchallenge", index=models.Index(fields=["email", "created_at"], name="pubinq_email_created_idx")),
        migrations.AddIndex(model_name="publicinquiry", index=models.Index(fields=["target_organization", "status", "created_at"], name="pubinq_target_status_idx")),
        migrations.AddIndex(model_name="publicinquiry", index=models.Index(fields=["sender_user", "created_at"], name="pubinq_sender_created_idx")),
    ]
