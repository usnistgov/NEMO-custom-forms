from NEMO.decorators import customization
from NEMO.views.customization import CustomizationBase


@customization(key="custom_forms", title="Custom Forms")
class CustomFormCustomization(CustomizationBase):
    files = [
        ("custom_form_action_required_email", ".html"),
        ("custom_form_received_email", ".html"),
        ("custom_form_status_update_email", ".html"),
    ]
