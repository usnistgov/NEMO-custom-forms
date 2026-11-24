from django.db import migrations, models
import django.db.models.deletion


def copy_table_columns_to_export_columns(apps, schema_editor):
    TableColumn = apps.get_model("NEMO_custom_forms", "CustomFormTableColumn")
    ExportColumn = apps.get_model("NEMO_custom_forms", "CustomFormExportColumn")
    ExportColumn.objects.bulk_create(
        ExportColumn(
            template_id=column.template_id,
            field_name=column.field_name,
            display_order=column.display_order,
            display_name=column.display_name,
        )
        for column in TableColumn.objects.all()
    )


class Migration(migrations.Migration):

    dependencies = [
        ("NEMO_custom_forms", "0007_alter_customformpdftemplate_form"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="CustomFormDisplayColumn",
            new_name="CustomFormTableColumn",
        ),
        migrations.AlterField(
            model_name="customformtablecolumn",
            name="field_name",
            field=models.CharField(
                help_text="The pdf template field name whose value will be used in the column", max_length=255
            ),
        ),
        migrations.AlterField(
            model_name="customformtablecolumn",
            name="display_name",
            field=models.CharField(
                blank=True,
                help_text="The column name. If not provided, the field name will be used",
                max_length=100,
                null=True,
            ),
        ),
        migrations.CreateModel(
            name="CustomFormExportColumn",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "field_name",
                    models.CharField(
                        help_text="The pdf template field name whose value will be used in the column", max_length=255
                    ),
                ),
                ("display_order", models.PositiveIntegerField(help_text="The display order of the column.")),
                (
                    "display_name",
                    models.CharField(
                        blank=True,
                        help_text="The column name. If not provided, the field name will be used",
                        max_length=100,
                        null=True,
                    ),
                ),
                (
                    "template",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="NEMO_custom_forms.customformpdftemplate"
                    ),
                ),
            ],
            options={
                "ordering": ["display_order"],
            },
        ),
        migrations.RunPython(copy_table_columns_to_export_columns, migrations.RunPython.noop),
    ]
