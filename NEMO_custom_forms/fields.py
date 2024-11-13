from typing import List, Tuple

from NEMO.fields import DatalistWidget
from django import forms
from django.contrib.auth.models import Group, Permission


class RoleGroupPermissionChoiceField(forms.ChoiceField):
    def __init__(self, *args, roles=True, groups=False, permissions=False, **kwargs):
        submitted_choices = kwargs.pop("choices", self.role_choices(roles, groups, permissions))
        submitted_widget = kwargs.pop("widget", DatalistWidget)
        super().__init__(*args, choices=submitted_choices, widget=submitted_widget, **kwargs)

    @classmethod
    def role_choices(cls, roles: bool, groups: bool, permissions: bool) -> List[Tuple[str, str]]:
        role_choice_list = [("", "---------")]
        if roles:
            role_choice_list.extend(
                [
                    ("is_staff", "Staff"),
                    ("is_user_office", "User Office"),
                    ("is_accounting_officer", "Accounting officers"),
                    ("is_facility_manager", "Facility managers"),
                    ("is_administrator", "Administrators"),
                ]
            )
        if groups:
            role_choice_list.extend(
                [(group_name, group_name) for group_name in Group.objects.values_list("name", flat=True)]
            )
        if permissions:
            role_choice_list.extend([(p["codename"], p["name"]) for p in Permission.objects.values("codename", "name")])
        return role_choice_list

    @classmethod
    def role_display(cls, role: str, roles=True, groups=False, permissions=False) -> str:
        for key, value in cls.role_choices(roles, groups, permissions):
            if key == role:
                return value
        return ""
