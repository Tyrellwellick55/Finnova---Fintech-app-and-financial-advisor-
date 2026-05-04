# Generated migration to add credit_limit field
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0004_alter_account_unique_together_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='credit_limit',
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=12),
        ),
    ]
