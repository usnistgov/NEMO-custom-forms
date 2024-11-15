from django.urls import include, path

from NEMO_custom_forms.views import custom_forms

urlpatterns = [
    path(
        "custom_forms/",
        include(
            [
                path("", custom_forms.custom_forms, name="custom_forms"),
                path("create/", custom_forms.create_custom_form, name="create_custom_form"),
                path(
                    "create/<int:pdf_template_id>/",
                    custom_forms.create_custom_form,
                    name="create_custom_form_with_template",
                ),
                path(
                    "<int:custom_form_id>/edit/",
                    custom_forms.create_custom_form,
                    name="edit_custom_form",
                ),
                path(
                    "<int:custom_form_id>/cancel/",
                    custom_forms.cancel_custom_form,
                    name="cancel_custom_form",
                ),
                path(
                    "<int:custom_form_id>/render_pdf/",
                    custom_forms.render_custom_form_pdf,
                    name="render_custom_form_pdf",
                ),
                path(
                    "<int:custom_form_id>/approval/",
                    custom_forms.create_custom_form,
                    name="approval_custom_form",
                ),
                path("templates/", custom_forms.custom_form_templates, name="custom_form_templates"),
                path(
                    "form_fields/<int:form_id>/<str:group_name>/",
                    custom_forms.form_fields_group,
                    name="custom_form_fields_group",
                ),
            ]
        ),
    )
]
