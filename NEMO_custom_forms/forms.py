from NEMO.fields import AdminAutocompleteSelectWidget
from django import forms

from NEMO_custom_forms.models import RoleGroupPermissionChoiceField


# ChoiceField implementation with roles, groups and permissions.
# Make sure to call refresh_choices() in admin otherwise new groups/permissions will not appear
class RoleGroupPermissionChoiceFormField(forms.ChoiceField):
    def __init__(self, *args, role_field: RoleGroupPermissionChoiceField, **kwargs):
        self.role_field = role_field
        submitted_choices = kwargs.pop("choices", self.role_field.role_choices())
        submitted_widget = kwargs.pop("widget", AdminAutocompleteSelectWidget(attrs={"style": "width: 400px;"}))
        super().__init__(*args, choices=submitted_choices, widget=submitted_widget, **kwargs)

    def refresh_choices(self):
        self.choices = self.role_field.role_choices()
