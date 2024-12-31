import json

from NEMO.mixins import ModelAdminRedirectMixin
from NEMO.models import User
from NEMO.widgets.dynamic_form import DynamicForm
from django import forms
from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from NEMO_custom_forms.models import (
    CustomForm,
    CustomFormAction,
    CustomFormActionRecord,
    CustomFormAutomaticNumbering,
    CustomFormDisplayColumn,
    CustomFormDocumentType,
    CustomFormDocuments,
    CustomFormPDFTemplate,
    CustomFormSpecialMapping,
)
from NEMO_custom_forms.utilities import custom_forms_current_numbers


class CustomFormActionFormset(forms.BaseInlineFormSet):
    model = CustomFormAction


class CustomFormSpecialMappingFormset(forms.BaseInlineFormSet):
    model = CustomFormSpecialMapping

    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.fields["field_value_action"].queryset = CustomFormAction.objects.filter(template=self.instance)


class CustomFormActionAdminInline(admin.TabularInline):
    model = CustomFormAction
    formset = CustomFormActionFormset


class CustomFormSpecialMappingAdminInline(admin.TabularInline):
    model = CustomFormSpecialMapping
    formset = CustomFormSpecialMappingFormset


class CustomFormDisplayColumnInline(admin.TabularInline):
    model = CustomFormDisplayColumn


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
class CustomFormPDFTemplateAdmin(ModelAdminRedirectMixin, admin.ModelAdmin):
    form = CustomFormPDFTemplateForm
    list_display = ["name", "enabled", "form"]
    list_filter = ["enabled"]
    readonly_fields = ["_pdf_form_fields", "_form_fields_preview"]
    inlines = [CustomFormActionAdminInline, CustomFormSpecialMappingAdminInline, CustomFormDisplayColumnInline]

    def _pdf_form_fields(self, obj: CustomFormPDFTemplate):
        if obj.form:
            container_id = f"toggle-fields-{obj.pk}"
            toggle_link = format_html(
                f'<a href="javascript:void(0);" onclick="$(\'#{container_id}\').toggle()">Show/Hide Fields</a>',
                container_id,
            )
            fields_list = "".join(
                f"<li style='list-style: initial'>{field}{(': ' + str(obj.pdf_form_field_states(field))) if obj.pdf_form_field_states(field) else ''}</li>"
                for field in obj.pdf_form_fields()
            )
            fields_container = format_html(
                '<div id="{}" style="display:none;"><ul style="margin-left:10px;">{}</ul></div>',
                container_id,
                mark_safe(fields_list),
            )
            return mark_safe(f"{toggle_link}<br>{fields_container}")
        return ""

    def _form_fields_preview(self, obj: CustomFormPDFTemplate):
        if obj.id:
            form_validity_div = '<div id="form_validity"></div>' if obj.form_fields else ""
            return mark_safe(
                '<div class="dynamic_form_preview">{}{}</div><div class="help dynamic_form_preview_help">Save form to preview form fields</div>'.format(
                    DynamicForm(obj.form_fields).render("custom_form_fields_group", obj.id),
                    form_validity_div,
                )
            )
        return ""


class CustomFormActionRecordFormset(forms.BaseInlineFormSet):
    model = CustomFormActionRecord

    def add_fields(self, form, index):
        super().add_fields(form, index)
        if hasattr(self.instance, "template"):
            form.fields["action"].queryset = CustomFormAction.objects.filter(template=self.instance.template)


class CustomFormActionRecordInline(admin.TabularInline):
    model = CustomFormActionRecord
    formset = CustomFormActionRecordFormset


class CustomFormDocumentsInline(admin.TabularInline):
    model = CustomFormDocuments
    extra = 1


@admin.register(CustomFormDocumentType)
class CustomFormDocumentTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "form_template", "display_order"]
    list_filter = ["form_template"]


@admin.register(CustomForm)
class CustomFormAdmin(admin.ModelAdmin):
    inlines = [CustomFormDocumentsInline, CustomFormActionRecordInline]
    list_display = ["form_number", "status", "last_updated", "creator", "template", "cancelled"]
    list_filter = [
        ("creator", admin.RelatedOnlyFieldListFilter),
        ("template", admin.RelatedOnlyFieldListFilter),
        "cancelled",
    ]
    date_hierarchy = "last_updated"


class CustomFormAutomaticNumberingForm(forms.ModelForm):

    class Meta:
        model = CustomFormAutomaticNumbering
        fields = "__all__"
        widgets = {
            "numbering_template": forms.Textarea(attrs={"rows": 4, "cols": 75}),
        }


@admin.register(CustomFormAutomaticNumbering)
class CustomFormAutomaticNumberingAdmin(admin.ModelAdmin):
    list_display = ["template", "enabled", "numbering_group", "numbering_per_user", "get_role_display"]
    list_filter = ["enabled", "numbering_per_user"]
    readonly_fields = ["custom_form_numbers"]
    form = CustomFormAutomaticNumberingForm

    @admin.display(description="Allowed role/group", ordering="role")
    def get_role_display(self, obj: CustomFormAutomaticNumbering):
        return obj.get_role_display()

    def custom_form_numbers(self, obj: CustomFormAutomaticNumbering):
        current_number = custom_forms_current_numbers(obj.template)
        display_list = ""
        if current_number:
            if obj.numbering_group and obj.numbering_per_user:
                for group, value in current_number.items():
                    display_list += f'<li style="list-style: inherit">{group}<ul style="margin-left: 20px">'
                    for user_id, number in value.items():
                        user = User.objects.filter(id=user_id).first()
                        user = user.username if user else user_id
                        display_list += f'<li style="list-style: inherit"><u>{user}</u>: {number}</li>'
                    display_list += "</ul></li>"
            elif obj.numbering_group:
                for group, number in current_number.items():
                    display_list += f'<li style="list-style: inherit"><u>{group}</u>: {number}</li>'
            elif obj.numbering_per_user:
                for user_id, number in current_number.items():
                    user = User.objects.filter(id=user_id).first()
                    user = user.username if user else user_id
                    display_list += f'<li style="list-style: inherit"><u>{user}</u>: {number}</li>'
            return mark_safe(f'Current form numbers:<ul style="margin-left: 20px">{display_list}</ul>')
        else:
            return "No current form numbers recorded"
