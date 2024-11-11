from __future__ import annotations

import json
import os
import re
from typing import KeysView, List, Optional, Set

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.template.defaultfilters import yesno
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from NEMO_custom_forms.customization import CustomFormCustomization
from NEMO_custom_forms.pdf_utils import (
    copy_and_fill_pdf_form,
    pdf_form_field_names,
    pdf_form_field_states_for_field,
    validate_is_pdf_form,
)
from NEMO.models import BaseCategory, BaseDocumentModel, BaseModel, SerializationByNameModel, User
from NEMO.utilities import document_filename_upload, format_datetime
from NEMO.views.constants import CHAR_FIELD_MAXIMUM_LENGTH, MEDIA_PROTECTED
from NEMO.widgets.dynamic_form import get_submitted_user_inputs, validate_dynamic_form_model

re_ends_with_number = r"\d+$"


class CustomFormPDFTemplate(SerializationByNameModel):
    enabled = models.BooleanField(default=True)
    name = models.CharField(
        max_length=CHAR_FIELD_MAXIMUM_LENGTH, unique=True, help_text=_("The unique name for this form template")
    )
    form = models.FileField(
        upload_to=document_filename_upload, validators=[validate_is_pdf_form], help_text=_("The pdf form")
    )
    form_fields = models.TextField(help_text=_("JSON formatted fields list"))

    def get_filename_upload(self, filename):
        from django.template.defaultfilters import slugify

        return f"{MEDIA_PROTECTED}/custom_forms/forms/{slugify(self.name)}.pdf"

    def pdf_form_fields(self) -> KeysView[str]:
        return pdf_form_field_names(self.form.file)

    def pdf_form_field_states(self, field_name: str) -> List[str]:
        return pdf_form_field_states_for_field(self.form.file, field_name)

    def form_fields_json(self) -> List:
        return json.loads(self.form_fields)

    def get_re_field_names(self) -> List[str]:
        field_names = []
        for field in self.form_fields_json():
            if field["type"] != "group":
                field_names.append(re.escape(field["name"]))
            else:
                for sub_field in field["questions"]:
                    # for group question, the match should be able to end with a number
                    field_names.append(re.escape(sub_field["name"]) + re_ends_with_number)
        return field_names

    def special_mappings_display(self):
        return "<br>".join([str(mapping) for mapping in self.customformspecialmapping_set.all()])

    def approvals_display(self):
        return "<br>".join(
            [
                f"Level {approval.level} approval: {approval.get_permission_display()}"
                for approval in self.customformapprovallevel_set.all()
            ]
        )

    def link(self):
        return self.form.url

    def filename(self):
        return os.path.basename(self.form.name)

    def clean(self):
        if self.form_fields:
            errors = validate_dynamic_form_model(self.form_fields, "custom_form_fields_group", self.id)
            if errors:
                raise ValidationError({"form_fields": error for error in errors})
            if self.form:
                pdf_form_fields = self.pdf_form_fields()
                for re_field_name in self.get_re_field_names():
                    if not any(re.match(re_field_name, pdf_field) for pdf_field in pdf_form_fields):
                        field_name = re_field_name.replace(re_ends_with_number, "")
                        errors.append(f"The field with name: {field_name} could not be found in the pdf fields")
            if errors:
                raise ValidationError({"form_fields": error for error in errors})

    def __str__(self):
        return self.name


class CustomFormApprovalLevel(BaseModel):
    template = models.ForeignKey(CustomFormPDFTemplate, on_delete=models.CASCADE)
    level = models.PositiveIntegerField(
        help_text=_("The approval level number. Approval will be asked in ascending order")
    )
    permission = models.CharField(
        max_length=CHAR_FIELD_MAXIMUM_LENGTH, help_text=_("The role/permission required for users to approve")
    )
    can_edit_form = models.BooleanField(
        default=True, help_text=_("Check this box if the reviewer can make changes to the form")
    )

    class Meta:
        ordering = ["template", "level"]
        unique_together = ["template", "level"]

    def clean(self):
        permission_keys = [p[0] for p in self.permission_choices()]
        if not self.permission or self.permission not in permission_keys:
            raise ValidationError({"permission": f"You must select one of the available permission"})

    def reviewers(self) -> Set[User]:
        if self.permission:
            active_users = User.objects.filter(is_active=True)
            if self.permission == "is_staff":
                return set(active_users.filter(is_staff=True))
            elif self.permission == "is_user_office":
                return set(active_users.filter(is_user_office=True))
            elif self.permission == "is_accounting_officer":
                return set(active_users.filter(is_accounting_officer=True))
            elif self.permission == "is_facility_manager":
                return set(active_users.filter(is_facility_manager=True))
            elif self.permission == "is_administrator":
                return set(active_users.filter(is_administrator=True))
            else:
                return set(
                    active_users.filter(
                        Q(user_permissions__codename=self.permission)
                        | Q(user_permissions__group__permissions__codename=self.permission)
                    )
                )
        return set()

    @classmethod
    def permission_choices(cls):
        role_choices = [
            ("", "---------"),
            ("is_staff", "Staff"),
            ("is_user_office", "User Office"),
            ("is_accounting_officer", "Accounting officers"),
            ("is_facility_manager", "Facility managers"),
            ("is_administrator", "Administrators"),
        ]
        permission_choices = [(p["codename"], p["name"]) for p in Permission.objects.values("name", "codename")]
        return [*role_choices, *permission_choices]

    def get_permission_display(self):
        for key, value in self.permission_choices():
            if key == self.permission:
                return value
        return ""

    def __str__(self):
        return f"{self.template.name} level {self.level} approval: {self.get_permission_display()}"


class CustomFormSpecialMapping(BaseModel):
    class FieldValue(object):
        FORM_CREATOR = "creator"
        FORM_CREATION_TIME = "creation_time"
        FORM_NUMBER = "number"
        FORM_APPROVED = "approved"
        FORM_APPROVED_BY = "approved_by"
        FORM_APPROVAL_TIME = "approval_time"
        Choices = (
            (FORM_CREATOR, "Form creator"),
            (FORM_CREATION_TIME, "Form creation time"),
            (FORM_NUMBER, "Form number"),
            (FORM_APPROVED, "Form approved/denied"),
            (FORM_APPROVED_BY, "Form approved/denied by"),
            (FORM_APPROVAL_TIME, "Form approval time"),
        )
        ApprovalValues = [FORM_APPROVED, FORM_APPROVED_BY, FORM_APPROVAL_TIME]

    template = models.ForeignKey(CustomFormPDFTemplate, on_delete=models.CASCADE)
    field_name = models.CharField(
        max_length=CHAR_FIELD_MAXIMUM_LENGTH, help_text=_("The pdf template field name to map this value to")
    )
    field_value = models.CharField(
        max_length=CHAR_FIELD_MAXIMUM_LENGTH, choices=FieldValue.Choices, help_text=_("The special value to map it to")
    )
    field_value_approval = models.ForeignKey(
        CustomFormApprovalLevel,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        help_text=_("The approval level (for approval mappings only)"),
    )
    field_value_boolean = models.CharField(
        max_length=CHAR_FIELD_MAXIMUM_LENGTH,
        null=True,
        blank=True,
        help_text=_("Comma separated values to map approved/denied states, i.e. 'Yes,No'"),
    )

    class Meta:
        ordering = ["field_name"]
        unique_together = ("template", "field_name")

    def clean(self):
        if self.field_value in self.FieldValue.ApprovalValues and not self.field_value_approval_id:
            raise ValidationError(
                {"field_value_approval": _("This field is required when using an approval field value")}
            )
        if self.field_value not in self.FieldValue.ApprovalValues and self.field_value_approval_id:
            raise ValidationError(
                {"field_value_approval": _("This field should be left blank when using non approval field values")}
            )
        if self.field_value_boolean and self.field_value != self.FieldValue.FORM_APPROVED:
            raise ValidationError(
                {"field_value_boolean": _("This field only applies to field value 'Form approved/denied'")}
            )
        if self.template_id:
            if self.field_name not in self.template.pdf_form_fields():
                raise ValidationError({"field_name": _("This field name could not be found in the template fields")})
            if self.field_value == self.FieldValue.FORM_APPROVED:
                try:
                    true_value = yesno(True, self.field_value_boolean)
                    false_value = yesno(False, self.field_value_boolean)
                    none_value = yesno(None, self.field_value_boolean)
                    states = self.template.pdf_form_field_states(self.field_name)
                    if states:
                        if true_value not in states:
                            raise ValidationError(
                                {
                                    "field_value_boolean": _(
                                        f"'{true_value}' is not a valid option for '{self.field_name}': {states}"
                                    )
                                }
                            )
                        elif false_value not in states:
                            raise ValidationError(
                                {
                                    "field_value_boolean": _(
                                        f"'{false_value}' is not a valid option for '{self.field_name}': {states}"
                                    )
                                }
                            )
                        elif none_value not in states:
                            raise ValidationError(
                                {
                                    "field_value_boolean": _(
                                        f"'{none_value}' is not a valid option for '{self.field_name}': {states}"
                                    )
                                }
                            )
                except ValidationError:
                    raise
                except Exception as e:
                    raise ValidationError({"field_value_boolean": str(e)})

    def get_value(self, custom_form: CustomForm):
        if self.field_value == self.FieldValue.FORM_CREATOR:
            return custom_form.creator.get_name()
        elif self.field_value == self.FieldValue.FORM_CREATION_TIME:
            return format_datetime(custom_form.creation_time, "SHORT_DATE_FORMAT")
        elif self.field_value == self.FieldValue.FORM_NUMBER:
            return custom_form.form_number or ""
        elif self.field_value in self.FieldValue.ApprovalValues:
            pass
            # approval = custom_form.get_approval_for_level(self.field_value_approval.level)
            # if self.field_value == self.FieldValue.FORM_APPROVED:
            # 	return yesno(approval.approved, self.field_value_boolean)
            # elif self.field_value == self.FieldValue.FORM_APPROVED_BY:
            # 	return approval.approved_by.get_name()
            # elif self.field_value == self.FieldValue.FORM_APPROVAL_TIME:
            # 	return format_datetime(approval.approval_time, "SHORT_DATE_FORMAT")

    def __str__(self):
        level = f" (level {self.field_value_approval.level})" if self.field_value_approval else ""
        return f"{self.field_name} -> {self.field_value}{level}"


class CustomForm(BaseModel):
    class FormStatus(object):
        PENDING = 0
        APPROVED = 1
        DENIED = 2
        FULFILLED = 3
        Choices = (
            (PENDING, "Pending"),
            (APPROVED, "Approved"),
            (DENIED, "Denied"),
            (FULFILLED, "Fulfilled"),
        )

    form_number = models.CharField(null=True, blank=True, max_length=CHAR_FIELD_MAXIMUM_LENGTH, unique=True)
    creation_time = models.DateTimeField(auto_now_add=True, help_text=_("The date and time when the form was created."))
    creator = models.ForeignKey(User, related_name="custom_forms_created", on_delete=models.CASCADE)
    last_updated = models.DateTimeField(auto_now=True, help_text=_("The last time this form was modified."))
    last_updated_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        related_name="custom_forms_updated",
        help_text=_("The last user who modified this form."),
        on_delete=models.SET_NULL,
    )
    status = models.IntegerField(choices=FormStatus.Choices, default=FormStatus.PENDING)
    template = models.ForeignKey(CustomFormPDFTemplate, on_delete=models.CASCADE)
    template_data = models.TextField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    cancelled = models.BooleanField(default=False, help_text=_("Indicates the form has been cancelled."))
    cancellation_time = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        User, related_name="custom_forms_cancelled", null=True, blank=True, on_delete=models.SET_NULL
    )
    cancellation_reason = models.CharField(null=True, blank=True, max_length=CHAR_FIELD_MAXIMUM_LENGTH)

    class Meta:
        ordering = ["-last_updated"]

    @property
    def name(self) -> str:
        return self.form_number or f"{self.get_status_display()} Form {self.id}"

    def next_approval_level(self) -> Optional[CustomFormApprovalLevel]:
        for approval_level in self.template.customformapprovallevel_set.order_by("level"):
            if not CustomFormApproval.objects.filter(approval_level=approval_level, custom_form=self).exists():
                return approval_level

    def next_approval_candidates(self) -> Set[User]:
        users = set()
        # cannot approve form unless it's in pending state
        if self.status == self.FormStatus.PENDING:
            # get first approval level that hasn't been completed
            level = self.next_approval_level()
            if level:
                users.update(level.reviewers())
        return users

    def get_approval_for_level(self, approval_level: int) -> CustomFormApproval:
        return self.customformapproval_set.filter(approval_level__level=approval_level).first()

    def get_filled_pdf_template(self) -> bytes:
        field_mappings = {}
        for special_mapping in self.template.customformspecialmapping_set.all():
            field_mappings[special_mapping.field_name] = special_mapping.get_value(self)

        field_mappings = {**field_mappings, **self.get_template_data_input()}

        return copy_and_fill_pdf_form(self.template.form.file, field_mappings)

    def get_template_data_input(self):
        form_inputs = get_submitted_user_inputs(self.template_data)
        data_input = {}
        for question_name, value in form_inputs.items():
            if isinstance(value, str):
                data_input[question_name] = value
            else:
                for i, input_values in enumerate(value, 1):
                    for name, input_value in input_values.items():
                        data_input[f"{name}{i}"] = input_value
        return data_input

    def process_approval(self, user: User, level: CustomFormApprovalLevel, approved: bool):
        approval = CustomFormApproval()
        approval.custom_form = self
        approval.approved_by = user
        approval.approved = bool(approved)
        approval.approval_level = level
        approval.save()
        # Denied, update status
        if not approved:
            self.status = self.FormStatus.DENIED
            self.save(update_fields=["status"])
        # No more approvals needed, mark as APPROVED
        if approved and not self.next_approval_level():
            self.status = self.FormStatus.APPROVED
            self.save(update_fields=["status"])

    def cancel(self, user: User, reason: str = None):
        self.cancelled = True
        self.cancelled_by = user
        self.cancellation_time = timezone.now()
        self.cancellation_reason = reason
        self.save()

    def __str__(self):
        return f"{self.name} by {self.creator}"


class CustomFormDocumentType(BaseCategory):
    pass


class CustomFormDocuments(BaseDocumentModel):
    custom_form = models.ForeignKey(CustomForm, on_delete=models.CASCADE)
    document_type = models.ForeignKey(CustomFormDocumentType, null=True, blank=True, on_delete=models.SET_NULL)

    def get_filename_upload(self, filename):
        return f"{MEDIA_PROTECTED}/custom_forms/{self.id}/{filename}"

    class Meta(BaseDocumentModel.Meta):
        verbose_name_plural = "Custom form documents"


class CustomFormApproval(BaseModel):
    custom_form = models.ForeignKey(CustomForm, on_delete=models.CASCADE)
    approval_level = models.ForeignKey(CustomFormApprovalLevel, on_delete=models.CASCADE)
    approval_time = models.DateTimeField(
        auto_now_add=True, help_text=_("The date and time when the form was approved/denied.")
    )
    approved_by = models.ForeignKey(
        User,
        related_name="custom_forms_reviewed",
        help_text=_("The user who approved the form"),
        on_delete=models.CASCADE,
    )
    approved = models.BooleanField(default=False, help_text=_("Whether this form was approved or not"))

    class Meta:
        ordering = ["-approval_time"]
        unique_together = ("custom_form", "approval_level")

    def clean(self):
        if self.custom_form_id:
            if self.custom_form.cancelled:
                raise ValidationError({"custom_form": _("This form was cancelled and cannot be approved")})
            if self.custom_form.status in [
                CustomForm.FormStatus.APPROVED,
                CustomForm.FormStatus.DENIED,
                CustomForm.FormStatus.FULFILLED,
            ]:
                raise ValidationError(
                    {"custom_form": _(f"This form has already been {self.custom_form.get_status_display().lower()}")}
                )
            if self.approval_level_id:
                if self.custom_form.next_approval_level() != self.approval_level:
                    raise ValidationError({"approval_level": _("This form has already been approved at this level")})
            if self.approved_by_id:
                self_approval_allowed = CustomFormCustomization.get_bool("custom_forms_self_approval_allowed")
                if not self_approval_allowed and self.approved_by == self.custom_form.creator:
                    raise ValidationError({"approved_by": _("The creator is not allowed to approve its own form")})
                if self.approved_by not in self.custom_form.next_approval_candidates():
                    raise ValidationError({"approved_by": _("This person is not allowed to approve this form")})
