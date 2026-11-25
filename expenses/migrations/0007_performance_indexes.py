from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0006_loanrecord'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='personalexpense',
            index=models.Index(fields=['user', 'date'], name='pe_user_date_idx'),
        ),
        migrations.AddIndex(
            model_name='sharedexpense',
            index=models.Index(fields=['group', 'date'], name='se_group_date_idx'),
        ),
        migrations.AddIndex(
            model_name='sharedexpense',
            index=models.Index(fields=['group', 'is_settled'], name='se_group_settled_idx'),
        ),
        migrations.AddIndex(
            model_name='loanrecord',
            index=models.Index(fields=['user', 'transaction_type', 'status'], name='lr_user_type_status_idx'),
        ),
    ]
