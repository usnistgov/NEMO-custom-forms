import json

from django import forms
from django.contrib import admin
from django.utils.safestring import mark_safe

from NEMO_custom_forms.models import (
    CustomForm,
    CustomFormApproval,
    CustomFormApprovalLevel,
    CustomFormAutomaticNumbering,
    CustomFormDocumentType,
    CustomFormDocuments,
    CustomFormPDFTemplate,
    CustomFormSpecialMapping,
)
from NEMO.fields import DatalistWidget
from NEMO.widgets.dynamic_form import DynamicForm

from NEMO_custom_forms.utilities import custom_forms_current_numbers


class CustomFormApprovalLevelFormset(forms.BaseInlineFormSet):
    model = CustomFormApprovalLevel

    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.fields["permission"] = forms.ChoiceField(
            choices=CustomFormApprovalLevel.permission_choices(), widget=DatalistWidget
        )


class CustomFormSpecialMappingFormset(forms.BaseInlineFormSet):
    model = CustomFormSpecialMapping

    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.fields["field_value_approval"].queryset = CustomFormApprovalLevel.objects.filter(template=self.instance)


class CustomFormApprovalLevelAdminInline(admin.TabularInline):
    model = CustomFormApprovalLevel
    formset = CustomFormApprovalLevelFormset


class CustomFormSpecialMappingAdminInline(admin.TabularInline):
    model = CustomFormSpecialMapping
    formset = CustomFormSpecialMappingFormset


class CustomFormPDFTemplateForm(forms.ModelForm):

    class Media:
        js = ("admin/dynamic_form_preview/dynamic_form_preview.js",)
        css = {"": ("admin/dynamic_form_preview/dynamic_form_preview.css",)}

    def clean_form_fields(self):
        form_fields = self.cleaned_data["form_fields"]
        try:
            return json.dumps(json.loads(form_fields), indent=4)
        except:
            pass
        return form_fields


@admin.register(CustomFormPDFTemplate)
class CustomFormPDFTemplateAdmin(admin.ModelAdmin):
    form = CustomFormPDFTemplateForm
    list_display = ["name", "enabled", "form"]
    list_filter = ["enabled"]
    readonly_fields = ["_form_fields_preview"]
    inlines = [CustomFormApprovalLevelAdminInline, CustomFormSpecialMappingAdminInline]

    def _form_fields_preview(self, obj: CustomFormPDFTemplate):
        if obj.id:
            form_validity_div = '<div id="form_validity"></div>' if obj.form_fields else ""
            return mark_safe(
                '<div class="dynamic_form_preview">{}{}</div><div class="help dynamic_form_preview_help">Save form to preview form fields</div>'.format(
                    DynamicForm(obj.form_fields).render("custom_form_fields_group", obj.id),
                    form_validity_div,
                )
            )


class CustomFormApprovalInline(admin.TabularInline):
    model = CustomFormApproval

    def __init__(self, parent_model, admin_site):
        super().__init__(parent_model, admin_site)


class CustomFormDocumentsInline(admin.TabularInline):
    model = CustomFormDocuments
    extra = 1


@admin.register(CustomFormDocumentType)
class CustomFormDocumentTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "display_order"]


@admin.register(CustomForm)
class CustomFormAdmin(admin.ModelAdmin):
    inlines = [CustomFormDocumentsInline, CustomFormApprovalInline]
    list_display = ["form_number", "status", "last_updated", "creator", "template", "cancelled"]
    list_filter = [
        ("creator", admin.RelatedOnlyFieldListFilter),
        ("template", admin.RelatedOnlyFieldListFilter),
        "cancelled",
    ]
    date_hierarchy = "last_updated"


@admin.register(CustomFormAutomaticNumbering)
class CustomFormAutomaticNumberingAdmin(admin.ModelAdmin):
    list_display = ["template", "enabled", "numbering_group", "numbering_per_user"]
    list_filter = ["enabled", "numbering_per_user"]
    readonly_fields = ["custom_form_numbers"]

    def custom_form_numbers(self, obj: CustomFormAutomaticNumbering):
        current_number = custom_forms_current_numbers(obj.template)
        if current_number:
            number_list = "".join([f"<li>{item}</li>" for item in current_number])
            return mark_safe(f"Current form numbers:<ul>{number_list}</ul>")
        else:
            return "No current form numbers recorded"
