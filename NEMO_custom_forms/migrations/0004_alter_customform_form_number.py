# Generated by Django 4.2.19 on 2025-03-13 16:16

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("NEMO_custom_forms", "0003_customformpdftemplate_notes_placeholder"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customform",
            name="form_number",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
