from django.apps import AppConfig


class CustomFormsConfig(AppConfig):
    name = "NEMO_custom_forms"
    verbose_name = "Custom Forms"

    def ready(self):
        """
        This code will be run when Django starts.
        """
        pass
