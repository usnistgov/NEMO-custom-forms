from __future__ import annotations

from NEMO.decorators import customization
from NEMO.views.customization import CustomizationBase


@customization(title="Custom forms", key="custom_forms")
class CustomFormCustomization(CustomizationBase):
    variables = {
        "custom_forms_view_staff": "",
        "custom_forms_view_user_office": "",
        "custom_forms_view_accounting_officer": "",
        "custom_forms_create_staff": "",
        "custom_forms_create_user_office": "",
        "custom_forms_create_accounting_officer": "",
        "custom_forms_self_approval_allowed": "",
    }
