from django.apps import AppConfig


class CustomFormsConfig(AppConfig):
    name = "NEMO_custom_forms"
    verbose_name = "Custom Forms"

    def ready(self):
        from NEMO.plugins.utils import add_dynamic_notification_types
        from NEMO_custom_forms.utilities import CUSTOM_FORM_NOTIFICATION

        add_dynamic_notification_types(
            [(CUSTOM_FORM_NOTIFICATION, "Custom forms action - notifies next action candidates")]
        )
