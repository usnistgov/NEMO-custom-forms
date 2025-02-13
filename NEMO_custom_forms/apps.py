from django.apps import AppConfig


class CustomFormsConfig(AppConfig):
    name = "NEMO_custom_forms"
    verbose_name = "Custom Forms"
    default_auto_field = "django.db.models.AutoField"
    plugin_id = 1100  # Used to make EmailCategory and other IntegerChoices ranges unique

    def ready(self):
        from django.utils.translation import gettext_lazy as _
        from NEMO.plugins.utils import (
            add_dynamic_notification_types,
            add_dynamic_email_categories,
            check_extra_dependencies,
        )
        from NEMO_custom_forms.utilities import CUSTOM_FORM_NOTIFICATION, CUSTOM_FORM_EMAIL_CATEGORY

        check_extra_dependencies(self.name, ["NEMO", "NEMO-CE"])

        add_dynamic_notification_types(
            [(CUSTOM_FORM_NOTIFICATION, _("Custom forms action - notifies next action candidates"))]
        )
        add_dynamic_email_categories([(CUSTOM_FORM_EMAIL_CATEGORY, _("Custom forms"))])
