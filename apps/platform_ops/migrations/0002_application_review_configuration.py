from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


def seed_application_review_configuration(apps, schema_editor):
    Configuration = apps.get_model("platform_ops", "ApplicationReviewConfiguration")
    Configuration.objects.get_or_create(
        singleton_key=1,
        defaults={"application_initial_review_target_hours": 27},
    )


def remove_seeded_application_review_configuration(apps, schema_editor):
    Configuration = apps.get_model("platform_ops", "ApplicationReviewConfiguration")
    Configuration.objects.filter(singleton_key=1).delete()


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("platform_ops", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ApplicationReviewConfiguration",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "singleton_key",
                    models.PositiveSmallIntegerField(default=1, editable=False, unique=True),
                ),
                (
                    "application_initial_review_target_hours",
                    models.PositiveSmallIntegerField(
                        default=27,
                        help_text="Initial application review target in hours. This never performs automatic approval.",
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(720),
                        ],
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="application_review_configuration_updates",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Application review configuration",
                "verbose_name_plural": "Application review configuration",
            },
        ),
        migrations.RunPython(
            seed_application_review_configuration,
            remove_seeded_application_review_configuration,
        ),
    ]
