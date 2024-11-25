from typing import Optional, Dict

from NEMO.decorators import administrator_required
from NEMO.exceptions import RequiredUnansweredQuestionsException
from NEMO.models import User
from NEMO.typing import QuerySetType
from NEMO.utilities import BasicDisplayTable, export_format_datetime, format_datetime, slugify_underscore
from NEMO.views.pagination import SortedPaginator
from NEMO.widgets.dynamic_form import DynamicForm, render_group_questions
from django import forms
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from NEMO_custom_forms.customization import CustomFormCustomization
from NEMO_custom_forms.models import (
    CustomForm,
    CustomFormDocuments,
    CustomFormPDFTemplate,
    CustomFormAutomaticNumbering,
)
from NEMO_custom_forms.utilities import merge_documents


def can_view_custom_forms(user) -> bool:
    staff = CustomFormCustomization.get_bool("custom_forms_view_staff")
    user_office = CustomFormCustomization.get_bool("custom_forms_view_user_office")
    accounting = CustomFormCustomization.get_bool("custom_forms_view_accounting_officer")
    return user.is_active and (
        staff
        and user.is_staff
        or user_office
        and user.is_user_office
        or accounting
        and user.is_accounting_officer
        or user.is_facility_manager
        or user.is_superuser
    )


def can_create_custom_forms(user: User) -> bool:
    staff = CustomFormCustomization.get_bool("custom_forms_create_staff")
    user_office = CustomFormCustomization.get_bool("custom_forms_create_user_office")
    accounting = CustomFormCustomization.get_bool("custom_forms_create_accounting_officer")
    return user.is_active and (
        staff
        and user.is_staff
        or user_office
        and user.is_user_office
        or accounting
        and user.is_accounting_officer
        or user.is_facility_manager
        or user.is_superuser
    )


class CustomFormForm(forms.ModelForm):

    def __init__(self, *args, template: CustomFormPDFTemplate = None, **kwargs):
        super().__init__(*args, **kwargs)
        # remove the form number field if there is already a form number or if it should be generated automatically
        existing_form_number = self.instance and self.instance.form_number
        auto_generate = (
            template
            and hasattr(template, "customformautomaticnumbering")
            and template.customformautomaticnumbering.enabled
        )
        if existing_form_number or auto_generate:
            self.fields.pop("form_number")

    class Meta:
        model = CustomForm
        exclude = [
            "status",
            "template",
            "template_data",
            "creator",
            "last_updated",
            "last_updated_by",
            "cancelled",
            "cancelled_by",
            "cancellation_time",
            "cancellation_reason",
        ]


@login_required
@user_passes_test(can_view_custom_forms)
@require_GET
def custom_forms(request, custom_form_template_id=None):
    selected_template = CustomFormPDFTemplate.objects.filter(id=custom_form_template_id).first()
    custom_form_list = CustomForm.objects.filter(cancelled=False)
    if selected_template:
        custom_form_list = custom_form_list.filter(template=selected_template)
    page = SortedPaginator(custom_form_list, request, order_by="-last_updated").get_current_page()

    if bool(request.GET.get("csv", False)):
        return export_custom_forms(custom_form_list.order_by("-last_updated"))

    dictionary = {
        "page": page,
        "user_can_add": can_create_custom_forms(request.user),
        **get_dictionary_for_base(selected_template),
    }
    return render(request, "NEMO_custom_forms/custom_forms.html", dictionary)


@administrator_required
@require_GET
def custom_form_templates(request):
    custom_form_template_list = CustomFormPDFTemplate.objects.filter(enabled=True)
    page = SortedPaginator(custom_form_template_list, request, order_by="name").get_current_page()

    dictionary = {"page": page, **get_dictionary_for_base(template=None, templates=True)}

    return render(request, "NEMO_custom_forms/custom_form_templates.html", dictionary)


def get_dictionary_for_base(template: Optional[CustomFormPDFTemplate], templates=False) -> Dict:
    return {
        "title": f"{template.name} forms" if template else "Template list" if templates else "All forms",
        "selected_template": template,
        "form_templates": CustomFormPDFTemplate.objects.filter(enabled=True),
    }


def export_custom_forms(custom_form_list: QuerySetType[CustomForm]):
    table = BasicDisplayTable()
    table.add_header(("form_number", "Form number")),
    table.add_header(("created_date", "Created date")),
    table.add_header(("created_by", "Created by")),
    table.add_header(("status", "Status")),
    table.add_header(("cancelled", "Cancelled")),
    table.add_header(("cancelled_by", "Cancelled by")),
    table.add_header(("cancellation_reason", "Cancellation reason")),
    table.add_header(("notes", "Notes")),
    table.add_header(("documents", "Documents")),
    for custom_form in custom_form_list:
        row = {
            "form_number": custom_form.form_number,
            "created_date": format_datetime(custom_form.creation_time, "SHORT_DATE_FORMAT"),
            "created_by": custom_form.creator,
            "status": custom_form.get_status_display(),
            "cancelled": format_datetime(custom_form.cancellation_time, "SHORT_DATE_FORMAT"),
            "cancelled_by": custom_form.cancelled_by,
            "cancellation_reason": custom_form.cancellation_reason,
            "notes": custom_form.notes or "",
            "documents": "\n".join([doc.full_link() for doc in custom_form.customformdocuments_set.all()]),
        }
        table.add_row(row)
    filename = f"custom_forms_{export_format_datetime()}.csv"
    response = table.to_csv()
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@require_http_methods(["GET", "POST"])
def create_custom_form(request, custom_form_template_id=None, custom_form_id=None):
    user: User = request.user
    is_approval = [state for state in ["approve_form", "deny_form"] if state in request.POST]

    try:
        custom_form: Optional[CustomForm] = CustomForm.objects.get(id=custom_form_id)
        form_template = custom_form.template
    except CustomForm.DoesNotExist:
        if is_approval:
            raise
        custom_form = None
        if not can_create_custom_forms(user):
            return redirect("landing")
        # only check for template if it's a new form
        templates: QuerySetType[CustomFormPDFTemplate] = CustomFormPDFTemplate.objects.all()
        try:
            if templates.count() == 1:
                form_template = templates.first()
            else:
                form_template = CustomFormPDFTemplate.objects.get(id=custom_form_template_id)
        except CustomFormPDFTemplate.DoesNotExist:
            return render(request, "NEMO_custom_forms/choose_template.html", {"form_templates": templates})

    # Return to custom forms if trying to approve but not allowed
    approval_level = custom_form.next_approval_level() if custom_form else None
    if is_approval and approval_level and not custom_form.can_approve(user):
        return redirect("landing")

    edit = bool(custom_form)

    form = CustomFormForm(request.POST or None, instance=custom_form, template=form_template)

    if edit and not custom_form.can_edit(user):
        # because this can be a GET, we need to initialize cleaned_data
        form.cleaned_data = getattr(form, "cleaned_data", {})
        if custom_form.cancelled:
            form.add_error(None, "You are not allowed to edit cancelled forms.")
        elif custom_form.status in [CustomForm.FormStatus.DENIED, CustomForm.FormStatus.FULFILLED]:
            form.add_error(None, f"You are not allowed to edit {custom_form.get_status_display().lower()} forms.")
        else:
            form.add_error(None, "You are not allowed to edit this form.")

    dictionary = {
        "dynamic_form_fields": DynamicForm(
            form_template.form_fields, custom_form.template_data if edit else None
        ).render("custom_form_fields_group", form_template.id),
        "selected_template": form_template,
        "approval_level": approval_level,
        "readonly": edit and not custom_form.can_edit(user),
    }

    if request.method == "POST":
        try:
            form.instance.template_data = DynamicForm(form_template.form_fields).extract(request)
        except RequiredUnansweredQuestionsException as e:
            form.add_error("template_data", e.msg)
        if form.is_valid():
            if not edit:
                form.instance.creator = user

            form.instance.last_updated_by = user
            form.instance.template = form_template

            with transaction.atomic():
                # all this need to happen at the same time or be rolled back
                # auto-generate form number, form saving, and approval

                automatic_numbering: CustomFormAutomaticNumbering = getattr(
                    form_template, "customformautomaticnumbering", None
                )
                auto_generate_parameter = request.POST.get("auto_generate", "false") == "true"
                if (not custom_form or not custom_form.form_number) and automatic_numbering and auto_generate_parameter:
                    form.instance.form_number = automatic_numbering.next_custom_form_number(user, save=True)

                if not is_approval or approval_level.can_edit_form:
                    new_custom_form = form.save()

                    # Handle file uploads
                    for f in request.FILES.getlist("form_documents"):
                        CustomFormDocuments.objects.create(document=f, custom_form=new_custom_form)
                    CustomFormDocuments.objects.filter(id__in=request.POST.getlist("remove_documents")).delete()

                    # TODO: create_custom_form_notification(new_custom_form)
                    # TODO: send_custom_form_received_email(request, new_custom_form, edit)
                if is_approval:
                    custom_form.process_approval(user, approval_level, is_approval == ["approve_form"])
            return redirect("custom_forms")
        else:
            if request.FILES.getlist("form_documents") or request.POST.get("remove_documents"):
                form.add_error(field=None, error="Custom form document changes were lost, please resubmit them.")

    # If GET request or form is not valid
    dictionary["form"] = form
    return render(request, "NEMO_custom_forms/custom_form.html", dictionary)


@login_required
@require_GET
def generate_custom_form_number(request, custom_form_template_id):
    custom_form_template = get_object_or_404(CustomFormPDFTemplate, pk=custom_form_template_id)
    automatic_numbering: CustomFormAutomaticNumbering = getattr(
        custom_form_template, "customformautomaticnumbering", None
    )
    if automatic_numbering:
        next_number = automatic_numbering.next_custom_form_number(request.user)
        if next_number:
            return JsonResponse({"form_number": next_number})
    return HttpResponseBadRequest("You are not allowed to generate this form number")


@login_required
@require_http_methods(["GET", "POST"])
def cancel_custom_form(request, custom_form_id):
    custom_form = get_object_or_404(CustomForm, pk=custom_form_id)
    user: User = request.user
    if custom_form.can_edit(user):
        custom_form.cancel(user)
    return redirect("custom_forms")


@login_required
@require_GET
def render_custom_form_pdf(request, custom_form_id):
    user: User = request.user
    custom_form = get_object_or_404(CustomForm, pk=custom_form_id)
    if not can_view_custom_forms(user) or not custom_form.can_edit(user) or not can_create_custom_forms(user):
        return redirect("landing")

    merged_pdf_bytes = merge_documents(
        [custom_form.get_filled_pdf_template(), *custom_form.customformdocuments_set.all()]
    )

    pdf_response = HttpResponse(content_type="application/pdf")
    pdf_response["Content-Disposition"] = (
        f"attachment; filename={slugify_underscore(custom_form.template.name)}_{custom_form.form_number}.pdf"
    )
    pdf_response.write(merged_pdf_bytes)
    return pdf_response


@login_required
@require_GET
def form_fields_group(request, form_id, group_name):
    template = get_object_or_404(CustomFormPDFTemplate, id=form_id)
    return HttpResponse(
        render_group_questions(request, template.form_fields, "custom_form_fields_group", form_id, group_name)
    )


# TODO: make document upload work with type
# TODO: maybe allow multiple permissions/groups
# TODO: make it optional to have a PDF form (generate it from the form itself)
