from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    class Theme(models.TextChoices):
        SYSTEM = "system", "System"
        LIGHT = "light", "Light"
        DARK = "dark", "Dark"

    class Language(models.TextChoices):
        ENGLISH = "en", "English"
        ARABIC = "ar", "Arabic"

    theme_preference = models.CharField(max_length=10, choices=Theme.choices, default=Theme.SYSTEM)
    language_preference = models.CharField(max_length=2, choices=Language.choices, default=Language.ENGLISH)

    def __str__(self):
        return self.get_full_name() or self.username
