from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0003_public_profile_revision"),
    ]

    operations = [
        migrations.AddField(
            model_name="onboardingapplication",
            name="initial_review_target_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RemoveConstraint(
            model_name="publicprofilerevision",
            name="unique_open_public_profile_revision",
        ),
        migrations.AlterField(
            model_name="publicprofilerevision",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("submitted", "Submitted"),
                    ("under_review", "Under review"),
                    ("changes_required", "Changes required"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                ],
                db_index=True,
                default="draft",
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="publicprofilerevision",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    status__in=[
                        "draft",
                        "submitted",
                        "under_review",
                        "changes_required",
                    ]
                ),
                fields=("organization",),
                name="unique_open_public_profile_revision",
            ),
        ),
    ]
