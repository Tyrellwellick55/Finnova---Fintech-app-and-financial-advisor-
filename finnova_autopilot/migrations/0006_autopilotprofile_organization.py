from django.db import migrations, models
import django.db.models.deletion


def add_autopilot_profile_organization_column(apps, schema_editor):
    AutopilotProfile = apps.get_model('finnova_autopilot', 'AutopilotProfile')
    Organization = apps.get_model('finnovaapp', 'Organization')

    with schema_editor.connection.cursor() as cursor:
        existing_columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor,
                AutopilotProfile._meta.db_table,
            )
        }

    if 'organization_id' in existing_columns:
        return

    field = models.ForeignKey(
        Organization,
        on_delete=django.db.models.deletion.CASCADE,
        null=True,
        blank=True,
        related_name='+',
    )
    field.set_attributes_from_name('organization')
    schema_editor.add_field(AutopilotProfile, field)


class Migration(migrations.Migration):

    dependencies = [
        ('finnovaapp', '0003_organization_segment'),
        ('finnova_autopilot', '0005_rename_appr_user_status_created_finnova_aut_user_id_77678f_idx'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_autopilot_profile_organization_column,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='autopilotprofile',
                    name='organization',
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='autopilot_profiles',
                        to='finnovaapp.organization',
                    ),
                ),
            ],
        ),
    ]
