# Generated by Django 4.2.19 on 2025-02-24 15:43

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("NEMO_custom_forms", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customformdocuments",
            name="display_order",
            field=models.IntegerField(
                default=1,
                help_text="The order in which the documents will be listed. Lower values are displayed first.",
            ),
        ),
    ]
