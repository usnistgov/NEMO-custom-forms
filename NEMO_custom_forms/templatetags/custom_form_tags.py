from NEMO.models import User
from django import template

from NEMO_custom_forms.models import CustomForm, CustomFormPDFTemplate, CustomFormAutomaticNumbering

register = template.Library()


@register.filter
def can_generate_custom_form_number(form_template: CustomFormPDFTemplate, user: User):
    if hasattr(form_template, "customformautomaticnumbering"):
        numbering: CustomFormAutomaticNumbering = form_template.customformautomaticnumbering
        return numbering.can_generate_custom_form_number(user)
    return False


@register.filter
def can_approve_custom_form(custom_form: CustomForm, user: User):
    return custom_form.can_approve(user)


@register.filter
def can_edit_custom_form(custom_form: CustomForm, user: User):
    return custom_form.can_edit(user)
