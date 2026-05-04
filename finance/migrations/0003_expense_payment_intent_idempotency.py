# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0002_alter_account_unique_together_account_organization_and_more'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='expense',
            constraint=models.UniqueConstraint(fields=('payment_intent',), name='uniq_expense_payment_intent'),
        ),
    ]
