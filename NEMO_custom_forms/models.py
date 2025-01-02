from __future__ import annotations

import json
import os
import re
from typing import KeysView, List, Optional

from NEMO.constants import CHAR_FIELD_LARGE_LENGTH, CHAR_FIELD_MEDIUM_LENGTH, CHAR_FIELD_SMALL_LENGTH
from NEMO.fields import DynamicChoicesCharField, RoleGroupPermissionChoiceField
from NEMO.models import BaseCategory, BaseDocumentModel, BaseModel, Customization, SerializationByNameModel, User
from NEMO.typing import QuerySetType
from NEMO.utilities import (
    document_filename_upload,
    format_datetime,
    quiet_int,
    update_media_file_on_model_update,
)
from NEMO.views.constants import CHAR_FIELD_MAXIMUM_LENGTH, MEDIA_PROTECTED
from NEMO.widgets.dynamic_form import (
    DynamicForm,
    PostUsageGroupQuestion,
    get_submitted_user_inputs,
    validate_dynamic_form_model,
)
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import models
from django.dispatch import receiver
from django.template import Context, Template
from django.template.defaultfilters import yesno
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from NEMO_custom_forms.pdf_utils import (
    copy_and_fill_pdf_form,
    get_pdf_form_field_names,
    get_pdf_form_field_states_for_field,
    validate_pdf_form,
)
from NEMO_custom_forms.utilities import (
    CUSTOM_FORM_CURRENT_NUMBER_PREFIX,
    CUSTOM_FORM_GROUP_PREFIX,
    CUSTOM_FORM_TEMPLATE_PREFIX,
    CUSTOM_FORM_USER_PREFIX,
)

re_ends_with_number = r"\d+$"


class CustomFormPDFTemplate(SerializationByNameModel):
    enabled = models.BooleanField(default=True)
    name = models.CharField(
        max_length=CHAR_FIELD_MEDIUM_LENGTH, unique=True, help_text=_("The unique name for this form template")
    )
    form = models.FileField(
        upload_to=document_filename_upload, validators=[validate_pdf_form], help_text=_("The pdf form")
    )
    form_fields = models.TextField(help_text=_("JSON formatted fields list"))

    def get_filename_upload(self, filename):
        from django.template.defaultfilters import slugify

        return f"{MEDIA_PROTECTED}/custom_forms/templates/{slugify(self.name)}.pdf"

    def pdf_form_fields(self) -> KeysView[str]:
        return get_pdf_form_field_names(self.form.file)

    def pdf_form_field_states(self, field_name: str) -> List[str]:
        return get_pdf_form_field_states_for_field(self.form.file, field_name)

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

    def actions_display(self):
        return "<br>".join(
            [
                f"Rank {action.rank}, action: {action.get_action_type_display()}, role: {action.get_role_display()}"
                for action in self.customformaction_set.all()
            ]
        )

    def link(self):
        return self.form.url

    def filename(self):
        return os.path.basename(self.form.name)

    def next_custom_form_number(self, user: User, save=False) -> str:
        if hasattr(self, "customformautomaticnumbering"):
            return self.customformautomaticnumbering.next_custom_form_number(user, save)

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

    class Meta:
        ordering = ["name"]


# These two auto-delete pdf files from filesystem when they are unneeded:
@receiver(models.signals.post_delete, sender=CustomFormPDFTemplate)
def auto_delete_file_on_form_template_delete(sender, instance: CustomFormPDFTemplate, **kwargs):
    """Deletes file from filesystem when corresponding `CustomFormPDFTemplate` object is deleted."""
    if instance.form:
        instance.form.delete(False)


@receiver(models.signals.pre_save, sender=CustomFormPDFTemplate)
def auto_update_file_on_form_template_change(sender, instance: CustomFormPDFTemplate, **kwargs):
    """Updates old file from filesystem when corresponding `CustomFormPDFTemplate` object is updated with new file."""
    return update_media_file_on_model_update(instance, "form")


class CustomFormAutomaticNumbering(BaseModel):
    template = models.OneToOneField(CustomFormPDFTemplate, on_delete=models.CASCADE)
    enabled = models.BooleanField(
        default=True, help_text=_("Uncheck this box to disable the automatic numbering sequence for this template")
    )
    numbering_group = models.IntegerField(
        null=True,
        blank=True,
        help_text=_(
            "Optional. Use this field (with the year number for example) to create separate numbering sequences when its value is changed."
        ),
    )
    numbering_per_user = models.BooleanField(
        default=False,
        help_text="Check this box to maintain a separate numbering sequence for each user who generates it.",
    )
    numbering_template = models.CharField(
        max_length=CHAR_FIELD_LARGE_LENGTH,
        default="{{ current_number|stringformat:'04d' }}",
        help_text=_(
            mark_safe(
                '<div style="margin-top: 10px">The numbering template. Provided variables include: <ul style="margin-left: 20px"><li style="list-style: inherit"><b>custom_form_template</b>: the custom form template instance</li><li style="list-style: inherit"><b>user</b>: the user triggering the sequence</li><li style="list-style: inherit"><b>numbering_group</b>: the numbering group for this sequence</li><li style="list-style: inherit"><b>current_number</b>: the current number for this sequence</li></ul></div>'
            )
        ),
    )
    role = RoleGroupPermissionChoiceField(
        null=True,
        blank=True,
        roles=True,
        groups=True,
        empty_label="Automatic upon creation",
        verbose_name="Role/Group",
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        help_text=_(
            "The role/group required for users to automatically generate the form number. Leave blank to generate it upon creation without user action."
        ),
    )

    # getting the actual Field instance, not the role value
    @classmethod
    def get_role_field(cls) -> RoleGroupPermissionChoiceField:
        return cls._meta.get_field("role")

    def generate_automatically(self) -> bool:
        return not self.role

    def get_role_display(self):
        return self.get_role_field().role_display(self.role)

    def can_generate_custom_form_number(self, user):
        return self.get_role_field().has_user_role(self.role, user)

    def next_custom_form_number(self, user: User, save=False) -> str:
        if self.enabled and (self.can_generate_custom_form_number(user) or self.generate_automatically()):
            current_number_customization = (
                f"{CUSTOM_FORM_CURRENT_NUMBER_PREFIX}_{CUSTOM_FORM_TEMPLATE_PREFIX}{self.template_id}"
            )
            if self.numbering_group:
                current_number_customization += f"_{CUSTOM_FORM_GROUP_PREFIX}{self.numbering_group}"
            if self.numbering_per_user:
                current_number_customization += f"_{CUSTOM_FORM_USER_PREFIX}{user.id}"
            current_number = Customization.objects.filter(name=current_number_customization).first()
            current_number_value = quiet_int(current_number.value, 0) if current_number else 0
            current_number_value += 1
            context = {
                "custom_form_template": self.template,
                "user": user,
                "numbering_group": self.numbering_group or "",
                "current_number": current_number_value,
            }
            if save:
                Customization(name=current_number_customization, value=current_number_value).save()
            form_number = Template(self.numbering_template).render(Context(context))
            return form_number

    def clean(self):
        try:
            fake_user = User(first_name="Testy", last_name="McTester", email="testy_mctester@gmail.com", id=1)
            self.next_custom_form_number(fake_user, save=False)
        except Exception as e:
            raise ValidationError(str(e))

    def __str__(self):
        return f"{self.template.name} automatic numbering"

    class Meta:
        ordering = ["template__name"]


class CustomFormAction(BaseModel):
    class ActionTypes(models.TextChoices):  # Inner Class
        APPROVAL = "approval", "Approval"
        NOTIFICATION = "acknowledgment", "Acknowledgment"

    template = models.ForeignKey(CustomFormPDFTemplate, on_delete=models.CASCADE)
    action_type = DynamicChoicesCharField(
        max_length=CHAR_FIELD_SMALL_LENGTH,
        choices=ActionTypes.choices,
        default=ActionTypes.APPROVAL,
        help_text=_("The action type"),
    )
    rank = models.PositiveIntegerField(
        help_text=_("The action rank number. Actions will be requested in ascending order")
    )
    role = RoleGroupPermissionChoiceField(
        roles=True,
        groups=True,
        verbose_name="Role/Group",
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        help_text=_("The role/group required for users to take the action"),
    )
    self_action_allowed = models.BooleanField(
        default=False,
        help_text=_(
            "Check this box to allow the user who creates the form to also take action on it (approve his own form for example)."
        ),
    )
    can_edit_form = models.BooleanField(
        default=True, help_text=_("Check this box if the candidate can make changes to the form")
    )

    class Meta:
        ordering = ["template", "rank"]
        unique_together = ["template", "rank"]

    def get_role_display(self):
        return self.get_role_field().role_display(self.role)

    @classmethod
    def get_role_field(cls) -> RoleGroupPermissionChoiceField:
        return cls._meta.get_field("role")

    def __str__(self):
        return f"{self.template.name} rank: {self.rank} action: {self.get_action_type_display()} role: {self.get_role_display()}"


class CustomFormSpecialMapping(BaseModel):
    class FieldValue(models.TextChoices):  # Inner Class
        FORM_CREATOR = "creator", "Form creator"
        FORM_CREATION_TIME = "creation_time", "Form creation time"
        FORM_NUMBER = "number", "Form number"
        FORM_ACTION_TAKEN = "action_taken", "Form action (approved/denied/acknowledged) taken"
        FORM_ACTION_TAKEN_BY = "action_taken_by", "Form action taken by"
        FORM_ACTION_TAKEN_TIME = "action_taken_time", "Form action taken time"

    action_values = [FieldValue.FORM_ACTION_TAKEN, FieldValue.FORM_ACTION_TAKEN_BY, FieldValue.FORM_ACTION_TAKEN_TIME]
    template = models.ForeignKey(CustomFormPDFTemplate, on_delete=models.CASCADE)
    field_name = models.CharField(
        max_length=CHAR_FIELD_MAXIMUM_LENGTH, help_text=_("The pdf template field name to map this value to")
    )
    field_value = DynamicChoicesCharField(
        max_length=CHAR_FIELD_MAXIMUM_LENGTH, choices=FieldValue.choices, help_text=_("The special value to map it to")
    )
    field_value_action = models.ForeignKey(
        CustomFormAction,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        help_text=_("The action (for action mappings only)"),
    )
    field_value_boolean = models.CharField(
        max_length=CHAR_FIELD_MAXIMUM_LENGTH,
        null=True,
        blank=True,
        help_text=_("Comma separated values to map approved/denied states, i.e. 'Yes,No'"),
    )

    class Meta:
        ordering = ["field_name"]
        unique_together = ["template", "field_name"]

    def clean(self):
        if self.field_value in self.action_values and not self.field_value_action_id:
            raise ValidationError({"field_value_action": _("This field is required when using an action field value")})
        if self.field_value not in self.action_values and self.field_value_action_id:
            raise ValidationError(
                {"field_value_action": _("This field should be left blank when using non action field values")}
            )
        if self.field_value_boolean and self.field_value != self.FieldValue.FORM_ACTION_TAKEN:
            raise ValidationError(
                {"field_value_boolean": _("This field only applies to field value 'Form action taken'")}
            )
        if self.template_id:
            if self.field_name not in self.template.pdf_form_fields():
                raise ValidationError({"field_name": _("This field name could not be found in the template fields")})
            if self.field_value == self.FieldValue.FORM_ACTION_TAKEN:
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
        elif self.field_value in self.action_values:
            action = custom_form.get_action_record_for_rank(self.field_value_action.rank)
            if action:
                if self.field_value == self.FieldValue.FORM_ACTION_TAKEN:
                    return yesno(action.action_result, self.field_value_boolean)
                elif self.field_value == self.FieldValue.FORM_ACTION_TAKEN_BY:
                    return action.action_taken_by.get_name()
                elif self.field_value == self.FieldValue.FORM_ACTION_TAKEN_TIME:
                    return format_datetime(action.action_time, "SHORT_DATE_FORMAT")
        return ""

    def __str__(self):
        rank = f" (level {self.field_value_action.rank})" if self.field_value_action else ""
        return f"{self.field_name} -> {self.field_value}{rank}"


class CustomFormDisplayColumn(BaseModel):
    template = models.ForeignKey(CustomFormPDFTemplate, on_delete=models.CASCADE)
    field_name = models.CharField(
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        help_text=_("The pdf template field name whose value will be displayed in the table"),
    )
    display_order = models.PositiveIntegerField(help_text=_("The display order of the column."))
    display_name = models.CharField(
        max_length=CHAR_FIELD_SMALL_LENGTH,
        null=True,
        blank=True,
        help_text=_("The column name to be displayed in the table. If not provided, the field name will be used"),
    )

    def clean(self):
        errors = {}
        if self.template_id:
            try:
                dynamic_fields = DynamicForm(self.template.form_fields)
                if self.field_name not in [
                    question.name
                    for question in dynamic_fields.questions
                    if not isinstance(question, PostUsageGroupQuestion)
                ]:
                    errors["field_name"] = _(
                        "This field name could not be found in the form fields (or is not an allowed field type)"
                    )
            except:
                # we are skipping this on purpose, since any errors from creating dynamic forms will be raised in the template itself
                pass
            if self.display_order in self.template.customformdisplaycolumn_set.exclude(id=self.id).values_list(
                "display_order", flat=True
            ):
                errors["display_order"] = _("This display order is already in use for another column")
        if errors:
            raise ValidationError(errors)

    class Meta:
        ordering = ["display_order"]


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

    def next_action(self) -> Optional[CustomFormAction]:
        for action in self.template.customformaction_set.order_by("rank"):
            if not CustomFormActionRecord.objects.filter(action=action, custom_form=self).exists():
                return action

    def get_action_record_for_rank(self, rank: int) -> CustomFormActionRecord:
        return self.customformactionrecord_set.filter(action__rank=rank).first()

    def get_filled_pdf_template(self) -> bytes:
        # we are splitting regular field mappings and "signature" mappings
        # signature mapping will be stamped with a cursive font instead of regular form filling
        field_mappings = {}
        signature_mappings = {}
        for special_mapping in self.template.customformspecialmapping_set.all():
            mapping_value = special_mapping.get_value(self)
            if mapping_value is None:
                mapping_value = ""
            if special_mapping.field_value == CustomFormSpecialMapping.FieldValue.FORM_ACTION_TAKEN_BY:
                signature_mappings[special_mapping.field_name] = mapping_value
            else:
                field_mappings[special_mapping.field_name] = mapping_value

        field_mappings = {**field_mappings, **self.get_template_data_input()}

        return copy_and_fill_pdf_form(self.template.form.file, field_mappings, signature_mappings)

    def get_template_data_input(self):
        form_inputs = get_submitted_user_inputs(self.template_data)
        data_input = {}
        for question_name, value in form_inputs.items():
            if isinstance(value, str):
                data_input[question_name] = value
            else:
                for i, input_values in enumerate(value, 1):
                    # special case if it's a list of one string, we set it as if that was just one string
                    # This is especially useful for checkboxes
                    if isinstance(input_values, str) and len(value) == 1:
                        data_input[f"{question_name}"] = input_values
                    elif isinstance(input_values, dict):
                        for name, input_value in input_values.items():
                            data_input[f"{name}{i}"] = input_value
        return data_input

    def process_action(self, user: User, action: CustomFormAction, action_value: bool):
        action_record = CustomFormActionRecord()
        action_record.custom_form = self
        action_record.action_taken_by = user
        action_record.action_result = bool(action_value)
        action_record.action = action
        action_record.save()
        # Denied, update status
        if not action_value:
            self.status = self.FormStatus.DENIED
            self.save(update_fields=["status"])
        # No more actions needed, mark as APPROVED
        if action_value and not self.next_action():
            self.status = self.FormStatus.APPROVED
            self.save(update_fields=["status"])

    def cancel(self, user: User, reason: str = None):
        self.cancelled = True
        self.cancelled_by = user
        self.cancellation_time = timezone.now()
        self.cancellation_reason = reason
        self.save()

    def can_take_action(self, user: User) -> bool:
        if not self.pk:
            return False
        if self.status != CustomForm.FormStatus.PENDING:
            return False
        action = self.next_action()
        if not action:
            return False
        if user == self.creator and not action.self_action_allowed:
            return False
        return action.get_role_field().has_user_role(action.role, user)

    def can_take_action_and_edit(self, user: User) -> bool:
        action = self.next_action()
        if not action:
            return False
        return self.can_take_action(user) and action.can_edit_form

    def can_edit(self, user: User) -> bool:
        if self.cancelled or self.status in [
            CustomForm.FormStatus.DENIED,
            CustomForm.FormStatus.FULFILLED,
        ]:
            return False
        return self.status == self.FormStatus.PENDING and self.creator == user or self.can_take_action_and_edit(user)

    def next_action_candidates(self) -> QuerySetType[User]:
        action = self.next_action()
        if not action:
            return User.objects.none()
        candidate_list = action.get_role_field().users_with_role(action.role)
        if not action.self_action_allowed:
            candidate_list = candidate_list.exclude(id=self.creator_id)
        return candidate_list

    def __str__(self):
        return f"{self.name} by {self.creator}"


class CustomFormDocumentType(BaseCategory):
    form_template = models.ForeignKey(
        CustomFormPDFTemplate,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text=_("Select a template this document type applies to. Leave blank for all."),
    )


class CustomFormDocuments(BaseDocumentModel):
    custom_form = models.ForeignKey(CustomForm, on_delete=models.CASCADE)
    document_type = models.ForeignKey(CustomFormDocumentType, null=True, blank=True, on_delete=models.SET_NULL)

    def get_filename_upload(self, filename):
        return f"{MEDIA_PROTECTED}/custom_forms/{self.custom_form_id}/{filename}"

    class Meta(BaseDocumentModel.Meta):
        verbose_name_plural = "Custom form documents"
        ordering = ["display_order", "document_type__display_order"]


class CustomFormActionRecord(BaseModel):
    custom_form = models.ForeignKey(CustomForm, on_delete=models.CASCADE)
    action = models.ForeignKey(CustomFormAction, on_delete=models.CASCADE)
    action_type = DynamicChoicesCharField(
        max_length=CHAR_FIELD_SMALL_LENGTH,
        choices=CustomFormAction.ActionTypes.choices,
        default=CustomFormAction.ActionTypes.APPROVAL,
        help_text=_("The action type"),
    )
    action_time = models.DateTimeField(
        auto_now_add=True, help_text=_("The date and time when the action was taken on this form.")
    )
    action_taken_by = models.ForeignKey(
        User,
        related_name="custom_forms_reviewed",
        help_text=_("The user who took the action"),
        on_delete=models.CASCADE,
    )
    action_result = models.BooleanField(default=False, help_text=_("Whether the action was approved/acknowledged"))

    class Meta:
        ordering = ["-action_time"]
        unique_together = ("custom_form", "action")

    def clean(self):
        if self.custom_form_id:
            if self.custom_form.cancelled:
                raise ValidationError(
                    {NON_FIELD_ERRORS: _("This form was cancelled and no further actions can be taken on it")}
                )
            if self.custom_form.status in [
                CustomForm.FormStatus.APPROVED,
                CustomForm.FormStatus.DENIED,
                CustomForm.FormStatus.FULFILLED,
            ]:
                raise ValidationError(
                    {NON_FIELD_ERRORS: _(f"This form has already been {self.custom_form.get_status_display().lower()}")}
                )
            if self.action_id:
                # TODO: check this validation
                if self.custom_form.next_action() != self.action:
                    raise ValidationError({"action": _("This action/rank has already been taken for this form")})
            if self.action_taken_by_id:
                if not self.action.self_action_allowed and self.action_taken_by == self.custom_form.creator:
                    raise ValidationError({"action_taken_by": _("The creator is not allowed to approve its own form")})
                if not self.custom_form.can_take_action(self.action_taken_by):
                    raise ValidationError({"action_taken_by": _("This person is not allowed to approve this form")})
