from collections import OrderedDict, defaultdict
from typing import Dict, List, Optional, Tuple

from NEMO.decorators import administrator_required
from NEMO.exceptions import RequiredUnansweredQuestionsException
from NEMO.models import EmailNotificationType, Notification, User
from NEMO.typing import QuerySetType
from NEMO.utilities import (
    BasicDisplayTable,
    export_format_datetime,
    format_datetime,
    get_full_url,
    get_model_instance,
    send_mail,
)
from NEMO.views.notifications import delete_notification
from NEMO.views.pagination import SortedPaginator
from NEMO.widgets.dynamic_form import DynamicForm, render_group_questions
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from NEMO_custom_forms.models import (
    CustomForm,
    CustomFormAction,
    CustomFormActionRecord,
    CustomFormAutomaticNumbering,
    CustomFormDocumentType,
    CustomFormDocuments,
    CustomFormPDFTemplate,
)
from NEMO_custom_forms.notifications import create_custom_form_notification
from NEMO_custom_forms.pdf_utils import merge_documents
from NEMO_custom_forms.utilities import (
    CUSTOM_FORM_EMAIL_CATEGORY,
    CUSTOM_FORM_NOTIFICATION,
    default_dict_to_regular_dict,
)


def available_templates_for_user_to_see(user) -> List[CustomFormPDFTemplate]:
    available_templates = []
    for available_template in CustomFormPDFTemplate.objects.filter(enabled=True):
        if (
            available_template.can_user_create(user)
            or available_template.can_user_view_all(user)
            or available_template.can_user_approve(user)
        ):
            available_templates.append(available_template)
    return available_templates


def available_templates_for_user_to_add(user) -> List[CustomFormPDFTemplate]:
    return [
        available_template
        for available_template in CustomFormPDFTemplate.objects.filter(enabled=True)
        if available_template.can_user_create(user)
    ]


def can_view_any_custom_forms(user) -> bool:
    return bool(available_templates_for_user_to_see(user))


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
@user_passes_test(can_view_any_custom_forms)
@require_GET
def custom_forms(request, custom_form_template_id=None):
    user: User = request.user
    selected_template = CustomFormPDFTemplate.objects.filter(id=custom_form_template_id).first()
    if not selected_template:
        # Select the first template that the user can see/create
        available_templates = available_templates_for_user_to_see(user)
        selected_template = available_templates[0] if available_templates else None
        if selected_template:
            return redirect("custom_forms", custom_form_template_id=selected_template.id)
        else:
            return redirect("custom_form_templates")
    else:
        custom_form_list = CustomForm.objects.filter(cancelled=False).filter(template=selected_template)

    if not selected_template.can_user_view_all(user) and not selected_template.can_user_approve(user):
        # Restrict the list to the ones users have created
        custom_form_list = custom_form_list.filter(creator=user)

    page = SortedPaginator(custom_form_list, request, order_by="-last_updated").get_current_page()

    if bool(request.GET.get("csv", False)):
        return export_custom_forms(request, selected_template, custom_form_list.order_by("-last_updated"))

    default_columns = [
        ("form_number", "Form number"),
        ("creation_time", "Created"),
        ("creator", "Creator"),
        ("status", "Status"),
    ]

    dictionary = {
        "page": page,
        "user_can_add": selected_template.can_user_create(user),
        "user_can_view_all": selected_template.can_user_view_all(user),
        "template_columns": get_ordered_columns(selected_template, default_columns),
        "default_columns": default_columns,
        **get_dictionary_for_base(request, selected_template),
    }
    return render(request, "NEMO_custom_forms/custom_forms.html", dictionary)


# Reorder columns to fill in the gaps with the provided default columns
def get_ordered_columns(selected_template: CustomFormPDFTemplate, default_columns: List[Tuple[str, str]]) -> Dict:
    template_columns = {
        column.display_order: (column.field_name, column.display_name)
        for column in selected_template.customformdisplaycolumn_set.all()
    }

    if not template_columns:
        return dict(enumerate(default_columns))

    max_index = max(template_columns.keys())

    gap_iter = iter(default_columns)

    for i in range(1, max_index + 1 + len(default_columns)):
        if i not in template_columns.keys():
            try:
                template_columns[i] = next(gap_iter)
            except StopIteration:
                # no more default columns to insert
                pass

    # order dict by key
    return OrderedDict(sorted(template_columns.items()))


@administrator_required
@require_GET
def custom_form_templates(request):
    custom_form_template_list = CustomFormPDFTemplate.objects.filter(enabled=True)
    page = SortedPaginator(custom_form_template_list, request, order_by="name").get_current_page()

    dictionary = {"page": page, **get_dictionary_for_base(request)}

    return render(request, "NEMO_custom_forms/custom_form_templates.html", dictionary)


def get_dictionary_for_base(request, template: CustomFormPDFTemplate = None) -> Dict:
    # Grab and organise notifications by template
    notifications = Notification.objects.filter(notification_type=CUSTOM_FORM_NOTIFICATION, user=request.user)
    custom_form_notifications = defaultdict(int)
    for notification in notifications:
        custom_form = get_model_instance(notification.content_type, notification.object_id)
        custom_form_notifications[custom_form.template_id] += 1

    return {
        "title": f"{template.name} forms" if template else "Template list",
        "selected_template": template,
        "form_templates": available_templates_for_user_to_see(request.user),
        "custom_form_notifications": default_dict_to_regular_dict(custom_form_notifications),
    }


def export_custom_forms(request, selected_template: CustomFormPDFTemplate, custom_form_list: QuerySetType[CustomForm]):
    table = BasicDisplayTable()
    default_columns = [
        ("form_number", "Form number"),
        ("creation_time", "Created on"),
        ("creator", "Creator"),
        ("status", "Status"),
    ]
    columns = get_ordered_columns(selected_template, default_columns).values()
    table.headers.extend([(column[0], column[1] or column[0]) for column in columns])
    table.add_header(("cancelled", "Cancelled on")),
    table.add_header(("cancelled_by", "Cancelled by")),
    table.add_header(("cancellation_reason", "Cancellation reason")),
    table.add_header(("notes", "Notes")),
    table.add_header(("document", "Document")),
    for action in selected_template.customformaction_set.all():
        table.add_header((f"action_{action.id}", action.label))
    for custom_form in custom_form_list:
        row = {
            "form_number": custom_form.form_number,
            "creation_time": format_datetime(custom_form.creation_time, "SHORT_DATETIME_FORMAT"),
            "creator": custom_form.creator,
            "status": custom_form.get_status_display(),
            "cancelled": (
                format_datetime(custom_form.cancellation_time, "SHORT_DATE_FORMAT") if custom_form.cancelled else ""
            ),
            "cancelled_by": custom_form.cancelled_by,
            "cancellation_reason": custom_form.cancellation_reason,
            "notes": custom_form.notes or "",
            "document": get_full_url(reverse("render_custom_form_pdf", args=[custom_form.pk]), request),
        }
        data_input = custom_form.get_template_data_input()
        for key in get_ordered_columns(selected_template, []).values():
            row[key[0]] = data_input.get(key[0])
        for action in selected_template.customformaction_set.all():
            action_record = custom_form.get_action_record_for_rank(action.rank)
            if action_record:
                row[f"action_{action.id}"] = (
                    f'{format_datetime(action_record.action_time, "SHORT_DATE_FORMAT")} by {action_record.action_taken_by.username}'
                )
        table.add_row(row)
    filename = f"custom_forms_{export_format_datetime()}.csv"
    response = table.to_csv()
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@require_http_methods(["GET", "POST"])
def create_custom_form(request, custom_form_template_id=None, custom_form_id=None):
    user: User = request.user
    action = CustomFormAction.objects.filter(id=request.POST.get("action_id")).first()

    try:
        custom_form: Optional[CustomForm] = CustomForm.objects.get(id=custom_form_id)
        form_template = custom_form.template
    except CustomForm.DoesNotExist:
        if action:
            raise
        templates: List[CustomFormPDFTemplate] = available_templates_for_user_to_add(user)
        custom_form = None
        try:
            if len(templates) == 1:
                form_template = templates[0]
            else:
                form_template = CustomFormPDFTemplate.objects.get(id=custom_form_template_id)
        except CustomFormPDFTemplate.DoesNotExist:
            return render(request, "NEMO_custom_forms/choose_template.html", {"form_templates": templates})

    # Check template permission
    if form_template not in available_templates_for_user_to_see(user):
        return redirect("landing")

    # Return to custom forms if trying to take action but not allowed
    if action and (not custom_form.can_take_action(user, action) or action != custom_form.next_action()):
        messages.error(request, "You are not allowed to take this action on this form.")
        redirect("custom_forms", custom_form_template_id=custom_form.template_id)

    edit = bool(custom_form)
    action_only = action and custom_form and custom_form.can_take_next_action(user) and not custom_form.can_edit(user)
    readonly = edit and not custom_form.can_edit(user)

    form = CustomFormForm(request.POST or None, instance=custom_form, template=form_template)

    if edit and not custom_form.can_edit(user) and not action_only:
        # because this can be a GET, we need to initialize cleaned_data
        form.cleaned_data = getattr(form, "cleaned_data", {})
        if custom_form.cancelled:
            form.add_error(None, "You are not allowed to edit cancelled forms.")
        elif custom_form.status in CustomForm.FormStatus.finished():
            form.add_error(None, f"You are not allowed to edit {custom_form.get_status_display().lower()} forms.")
        else:
            form.add_error(None, "You are not allowed to edit this form.")

    dictionary = {
        "dynamic_form_fields": DynamicForm(
            form_template.form_fields, custom_form.template_data if edit else None
        ).render("custom_form_fields_group", form_template.id),
        "selected_template": form_template,
        "action": custom_form.next_action() if custom_form and custom_form.can_take_next_action(user) else None,
        "document_types": CustomFormDocumentType.objects.filter(
            Q(form_template=form_template) | Q(form_template__isnull=True)
        ),
        "custom_form_documents": (
            custom_form.customformdocuments_set.order_by("display_order", "document_type__display_order")
            if custom_form
            else []
        ),
        "readonly": readonly,
    }

    if request.method == "POST":
        try:
            if not readonly:
                try:
                    form.instance.template_data = DynamicForm(form_template.form_fields).extract(request)
                except RequiredUnansweredQuestionsException as e:
                    form.add_error(field=None, error=e.msg)
            if form.is_valid():
                if not edit and not form.instance.creator_id:
                    form.instance.creator = user

                if not action_only:
                    form.instance.last_updated_by = user
                form.instance.template = form_template

                with transaction.atomic():
                    # all this need to happen at the same time or be rolled back
                    # auto-generate form number, form saving, and actions

                    automatic_numbering: CustomFormAutomaticNumbering = getattr(
                        form_template, "customformautomaticnumbering", None
                    )
                    auto_generate_parameter = request.POST.get("auto_generate", "false") == "true"
                    if (
                        (not custom_form or not custom_form.form_number)
                        and automatic_numbering
                        and auto_generate_parameter
                    ):
                        if automatic_numbering.role and not automatic_numbering.get_role_field().has_user_role(
                            automatic_numbering.role, user
                        ):
                            return HttpResponseForbidden(
                                "You are not allowed to generate a form number for this form template."
                            )
                        form.instance.form_number = automatic_numbering.next_custom_form_number(user, save=True)

                    if not action or action.can_edit_form:
                        custom_form = form.save()

                        # Handle file uploads
                        document_type_id = request.POST.get("document_type_id", None) or None
                        document_type = CustomFormDocumentType.objects.filter(id=document_type_id).first()
                        for f in request.FILES.getlist("form_documents"):
                            CustomFormDocuments.objects.create(
                                document=f, custom_form=custom_form, document_type=document_type
                            )
                        CustomFormDocuments.objects.filter(id__in=request.POST.getlist("remove_documents")).delete()
                    if action:
                        delete_notification(CUSTOM_FORM_NOTIFICATION, custom_form.id)
                        action_record = custom_form.process_action(user, action, request.POST.get("action_result"))
                        send_custom_form_status_update(request, action, action_record)
                    create_custom_form_notification(custom_form)
                    send_custom_form_notification_email(request, custom_form, edit)
                return redirect("custom_forms", custom_form_template_id=custom_form.template_id)
            else:
                if request.FILES.getlist("form_documents") or request.POST.get("remove_documents"):
                    raise ValidationError("Custom form document changes were lost, please resubmit them.")
        except ValidationError as e:
            form.add_error(field=None, error=e)

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
def delete_custom_form(request, custom_form_id):
    custom_form = get_object_or_404(CustomForm, pk=custom_form_id)
    user: User = request.user
    if custom_form.can_edit(user):
        custom_form.cancel(user)
    return redirect("custom_forms", custom_form_template_id=custom_form.template_id)


@login_required
@require_GET
def render_custom_form_pdf(request, custom_form_id):
    user: User = request.user
    custom_form = get_object_or_404(CustomForm, pk=custom_form_id)
    if (
        not custom_form.template.can_user_view_all(user)
        and not custom_form.template.can_user_approve(user)
        and not custom_form.creator == user
    ):
        return redirect("landing")

    merged_pdf_bytes = merge_documents(
        [custom_form.get_filled_pdf_template(), *custom_form.customformdocuments_set.all()]
    )

    pdf_response = HttpResponse(content_type="application/pdf")
    pdf_response["Content-Disposition"] = f"attachment; filename={custom_form.rendered_filename()}.pdf"
    pdf_response.write(merged_pdf_bytes)
    return pdf_response


@login_required
@require_GET
def form_fields_group(request, form_id, group_name):
    template = get_object_or_404(CustomFormPDFTemplate, id=form_id)
    return HttpResponse(
        render_group_questions(request, template.form_fields, "custom_form_fields_group", form_id, group_name)
    )


def send_custom_form_notification_email(request, custom_form: CustomForm, edit):
    # First, send form received to creator
    absolute_url_forms = get_full_url(reverse("custom_forms", args=[custom_form.template_id]), request)
    if not edit:
        send_mail(
            subject=f"{custom_form.template.name} #{custom_form.form_number or custom_form.id} has been received",
            content=f"""Dear {custom_form.creator.first_name},
<br><br>
Thank you for submitting a new {custom_form.template.name}.
<br><br>
You can follow the status of your {custom_form.template.name} <a href="{absolute_url_forms}">here</a>.              
""",
            from_email=None,
            to=custom_form.creator.get_emails(EmailNotificationType.BOTH_EMAILS),
            email_category=CUSTOM_FORM_EMAIL_CATEGORY,
        )
    # Second, notify users who can deal with the next action
    users_to_notify = set(custom_form.next_action_candidates())
    if users_to_notify:
        absolute_url_action = get_full_url(reverse("custom_form_action", args=[custom_form.id]), request)
        send_mail(
            subject=f"{custom_form.template.name} #{custom_form.form_number or custom_form.id}: action required",
            content=f"""Please follow <a href="{absolute_url_action}">this link</a> to take the next action for this {custom_form.template.name}.
""",
            from_email=None,
            to=[email for user in users_to_notify for email in user.get_emails(EmailNotificationType.BOTH_EMAILS)],
            email_category=CUSTOM_FORM_EMAIL_CATEGORY,
        )


def send_custom_form_status_update(request, action: CustomFormAction, action_record: CustomFormActionRecord):
    # get ccs from action
    ccs = action.notification_email
    custom_form = action_record.custom_form
    absolute_url_forms = get_full_url(reverse("custom_forms", args=[custom_form.template_id]), request)
    number_of_actions = custom_form.template.customformaction_set.count()
    number_of_actions_recorded = custom_form.customformactionrecord_set.count()
    send_mail(
        subject=f"{custom_form.template.name} #{custom_form.form_number or custom_form.id}: status update ({number_of_actions_recorded} of {number_of_actions})",
        content=f"""Dear {custom_form.creator.first_name},
<br><br>
{action_record.action_taken_by.first_name} has completed the following action: {action.label}.
<br><br>
You can follow the status of your {custom_form.template.name} <a href="{absolute_url_forms}">here</a>.              
""",
        from_email=None,
        to=custom_form.creator.get_emails(EmailNotificationType.BOTH_EMAILS),
        bcc=ccs,
        email_category=CUSTOM_FORM_EMAIL_CATEGORY,
    )


# TODO: make it optional to have a PDF form (generate it from the form itself)
# TODO: add filters in custom form page
