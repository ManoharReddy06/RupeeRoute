import datetime
from decimal import Decimal
import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('expenses', '0005_sharedexpense_is_settled_sharedexpense_settled_at_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='LoanRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('transaction_type', models.CharField(choices=[('given', 'Given to Others (Money Lent / I Gave)'), ('taken', 'Taken from Others (Money Borrowed / I Took)')], default='given', max_length=10)),
                ('person_name', models.CharField(help_text='Name of the person', max_length=150)),
                ('phone', models.CharField(blank=True, help_text='Optional phone number', max_length=20, null=True)),
                ('amount', models.DecimalField(decimal_places=2, help_text='Principal amount', max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))])),
                ('given_date', models.DateField(default=datetime.date.today, help_text='Date money was given / taken')),
                ('expected_return_date', models.DateField(blank=True, help_text='Expected repayment date', null=True)),
                ('has_interest', models.BooleanField(default=False, help_text='Whether interest is charged/payable')),
                ('interest_rate', models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='Interest percentage', max_digits=6)),
                ('interest_period', models.CharField(choices=[('month', 'Per Month'), ('year', 'Per Year (Per Annum)')], default='month', help_text="'month' or 'year'", max_length=10)),
                ('duration_value', models.PositiveIntegerField(default=1, help_text='Duration count (e.g. 6)')),
                ('duration_unit', models.CharField(choices=[('months', 'Months'), ('years', 'Years')], default='months', help_text="'months' or 'years'", max_length=10)),
                ('notes', models.TextField(blank=True, help_text='Optional description / reason')),
                ('status', models.CharField(choices=[('pending', 'Pending (Active)'), ('settled', 'Settled (Cleared / Returned)')], default='pending', max_length=20)),
                ('settled_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='loan_records', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-given_date', '-id'],
            },
        ),
    ]
