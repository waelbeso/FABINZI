from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("organizations", "0001_initial")]

    operations = [
        migrations.RenameIndex(
            model_name="membership",
            old_name="organizatio_user_id_c945bc_idx",
            new_name="organizatio_user_id_9eceb5_idx",
        ),
        migrations.RenameIndex(
            model_name="membership",
            old_name="organizatio_organiz_76ec4d_idx",
            new_name="organizatio_organiz_e82976_idx",
        ),
        migrations.RenameIndex(
            model_name="onboardingapplication",
            old_name="organizatio_status_3ea338_idx",
            new_name="organizatio_status_6f132b_idx",
        ),
        migrations.RenameIndex(
            model_name="organization",
            old_name="organizatio_kind_f69db6_idx",
            new_name="organizatio_kind_05b7f8_idx",
        ),
    ]
