# Generated by Django 3.2.16 on 2023-01-15 14:04

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('company', '0051_alter_supplierpricebreak_price'),
    ]

    operations = [
        migrations.AlterField(
            model_name='supplierpricebreak',
            name='updated',
            field=models.DateTimeField(auto_now=True, help_text='Timestamp of last update', null=True, verbose_name='Updated'),
        ),
    ]
