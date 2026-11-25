import csv
from datetime import datetime
from io import StringIO
from unittest.mock import Mock

from NEMO.models import Customization
from NEMO.tests.test_utilities import create_user_and_project
from django.apps import apps
from django.contrib import admin
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from NEMO_custom_forms.admin import CustomFormAdmin, duplicate_custom_form_template
from NEMO_custom_forms.models import (
    CustomForm,
    CustomFormAction,
    CustomFormActionRecord,
    CustomFormAutomaticNumbering,
    CustomFormDocuments,
    CustomFormExportColumn,
    CustomFormPDFTemplate,
    CustomFormTableColumn,
)
from NEMO_custom_forms.utilities import CUSTOM_FORM_CURRENT_NUMBER_PREFIX, custom_forms_current_numbers
from NEMO_custom_forms.views.custom_forms import export_custom_forms, get_ordered_columns


class CustomFormsTest(TestCase):

    def test_plugin_is_installed(self):
        assert apps.is_installed("NEMO_custom_forms")

    def setUp(self):
        self.user, self.project = create_user_and_project(is_staff=True)

    def create_date_filter_template(self):
        return CustomFormPDFTemplate.objects.create(
            name="Date filter template", form_fields="[]", view_all_permissions=["is_staff"]
        )

    def create_form_at(self, template, form_number, creation_time, creator=None, status=CustomForm.FormStatus.PENDING):
        custom_form = CustomForm.objects.create(
            template=template, creator=creator or self.user, form_number=form_number, status=status
        )
        CustomForm.objects.filter(pk=custom_form.pk).update(creation_time=creation_time)
        return custom_form

    def get_form_list(self, template, params):
        self.client.force_login(self.user)
        return self.client.get(reverse("custom_forms", kwargs={"custom_form_template_id": template.pk}), params)

    def test_custom_form_admin_view_link_uses_existing_form_view(self):
        template = CustomFormPDFTemplate.objects.create(name="Form view link")
        custom_form = CustomForm.objects.create(template=template, creator=self.user)
        form_url = reverse("edit_custom_form", kwargs={"custom_form_id": custom_form.pk})

        self.assertEqual(custom_form.get_absolute_url(), form_url)
        self.assertIn("get_link", CustomFormAdmin.list_display)
        custom_form_admin = CustomFormAdmin(CustomForm, admin.site)
        self.assertIn(form_url, custom_form_admin.get_link(custom_form))
        self.assertEqual(self.client.get(form_url).status_code, 302)

    def test_table_and_export_columns_are_independent(self):
        template = CustomFormPDFTemplate.objects.create(
            name="Column separation",
            form_fields='[{"name": "table_field", "type": "text"}, {"name": "export_field", "type": "text"}]',
        )
        table_column = CustomFormTableColumn.objects.create(
            template=template, field_name="table_field", display_order=1, display_name="Table field"
        )
        export_column = CustomFormExportColumn(
            template=template, field_name="export_field", display_order=1, display_name="Export field"
        )
        export_column.full_clean()
        export_column.save()

        default_columns = [
            ("form_number", "Form number"),
            ("creation_time", "Created"),
            ("creator", "Creator"),
            ("status", "Status"),
        ]
        table_columns = get_ordered_columns(template.customformtablecolumn_set.all(), default_columns)
        self.assertEqual(table_columns[1], (table_column.field_name, table_column.display_name))

        response = export_custom_forms(RequestFactory().get("/"), template, CustomForm.objects.none())
        csv_headers = [header.lower() for header in next(csv.reader(StringIO(response.content.decode())))]
        self.assertIn("export field", csv_headers)
        self.assertNotIn("table field", csv_headers)

    def test_creation_date_filters_are_inclusive_and_used_for_csv_export(self):
        template = self.create_date_filter_template()
        local_timezone = timezone.get_current_timezone()
        start_of_day = timezone.make_aware(datetime(2025, 1, 1, 0, 0), local_timezone)
        end_of_day = timezone.make_aware(datetime(2025, 1, 1, 23, 59, 59), local_timezone)
        next_day = timezone.make_aware(datetime(2025, 1, 2, 0, 0, 1), local_timezone)
        self.create_form_at(template, "at-start", start_of_day)
        self.create_form_at(template, "at-end", end_of_day)
        self.create_form_at(template, "next-day", next_day)

        response = self.get_form_list(template, {"start": "01/01/2025", "end": "01/01/2025"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual({form.form_number for form in response.context["page"]}, {"at-start", "at-end"})

        response = self.get_form_list(template, {"start": "01/01/2025", "end": "01/01/2025", "csv": "true"})
        exported_form_numbers = {row[0] for row in list(csv.reader(StringIO(response.content.decode())))[1:]}
        self.assertEqual(exported_form_numbers, {"at-start", "at-end"})

    def test_creation_date_filters_allow_open_ended_and_empty_ranges(self):
        template = self.create_date_filter_template()
        local_timezone = timezone.get_current_timezone()
        first_day = timezone.make_aware(datetime(2025, 1, 1, 12, 0), local_timezone)
        second_day = timezone.make_aware(datetime(2025, 1, 2, 12, 0), local_timezone)
        self.create_form_at(template, "first-day", first_day)
        self.create_form_at(template, "second-day", second_day)

        no_filter = self.get_form_list(template, {})
        start_only = self.get_form_list(template, {"start": "01/02/2025"})
        end_only = self.get_form_list(template, {"end": "01/01/2025"})

        self.assertEqual({form.form_number for form in no_filter.context["page"]}, {"first-day", "second-day"})
        self.assertEqual({form.form_number for form in start_only.context["page"]}, {"second-day"})
        self.assertEqual({form.form_number for form in end_only.context["page"]}, {"first-day"})

    def test_date_filters_combine_with_status_ownership_and_pagination(self):
        template = self.create_date_filter_template()
        in_range = timezone.make_aware(datetime(2025, 1, 1, 12, 0), timezone.get_current_timezone())
        out_of_range = timezone.make_aware(datetime(2025, 1, 2, 12, 0), timezone.get_current_timezone())
        another_user, _ = create_user_and_project(is_staff=False)
        self.create_form_at(template, "approved-one", in_range, status=CustomForm.FormStatus.APPROVED)
        self.create_form_at(template, "approved-two", in_range, status=CustomForm.FormStatus.APPROVED)
        self.create_form_at(template, "pending", in_range)
        self.create_form_at(template, "outside", out_of_range, status=CustomForm.FormStatus.APPROVED)
        self.create_form_at(
            template, "other-user", in_range, creator=another_user, status=CustomForm.FormStatus.APPROVED
        )

        params = {
            "start": "01/01/2025",
            "end": "01/01/2025",
            "form_status": str(CustomForm.FormStatus.APPROVED),
            "only_show_my_requests": "on",
            "pp": "1",
        }
        response = self.get_form_list(template, params)

        page_form_numbers = {form.form_number for form in response.context["page"]}
        self.assertEqual(len(page_form_numbers), 1)
        self.assertTrue(page_form_numbers.issubset({"approved-one", "approved-two"}))
        self.assertContains(response, "start=01%2F01%2F2025")
        self.assertContains(response, "form_status=1")

        export_response = self.get_form_list(template, {**params, "csv": "true"})
        exported_form_numbers = {row[0] for row in list(csv.reader(StringIO(export_response.content.decode())))[1:]}
        self.assertEqual(exported_form_numbers, {"approved-one", "approved-two"})

    def test_all_list_filters_are_bound_and_applied_to_csv(self):
        template = self.create_date_filter_template()
        CustomFormAction.objects.create(template=template, rank=1, role="is_staff")
        CustomFormAction.objects.create(template=template, rank=2, role="is_staff")
        another_user, _ = create_user_and_project(is_staff=False)
        current_action_form = self.create_form_at(template, "mine-current-action", timezone.now())
        other_user_form = self.create_form_at(
            template, "other-user-current-action", timezone.now(), creator=another_user
        )
        self.create_form_at(template, "mine-first-action", timezone.now())
        for custom_form in (current_action_form, other_user_form):
            CustomFormActionRecord.objects.create(
                custom_form=custom_form, action_rank=1, action_taken_by=self.user, action_result=True
            )

        params = {"form_status": "0", "form_action_rank": "2", "only_show_my_requests": "on"}
        response = self.get_form_list(template, params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual({form.form_number for form in response.context["page"]}, {"mine-current-action"})
        filter_form = response.context["filter_form"]
        self.assertEqual(filter_form["form_status"].value(), "0")
        self.assertEqual(filter_form["form_action_rank"].value(), "2")
        self.assertTrue(filter_form["only_show_my_requests"].value())

        export_response = self.get_form_list(template, {**params, "csv": "true"})
        exported_form_numbers = {row[0] for row in list(csv.reader(StringIO(export_response.content.decode())))[1:]}
        self.assertEqual(exported_form_numbers, {"mine-current-action"})

    def test_invalid_status_or_action_filter_does_not_show_forms_or_export(self):
        template = self.create_date_filter_template()
        CustomFormAction.objects.create(template=template, rank=1, role="is_staff")
        CustomFormAction.objects.create(template=template, rank=2, role="is_staff")
        self.create_form_at(template, "existing-form", timezone.now())

        for params, invalid_field in (
            ({"form_status": "999"}, "form_status"),
            ({"form_action_rank": "99"}, "form_action_rank"),
        ):
            with self.subTest(params=params):
                response = self.get_form_list(template, params)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.context["page"].object_list)
                self.assertIn(invalid_field, response.context["filter_form"].errors)

                export_response = self.get_form_list(template, {**params, "csv": "true"})
                self.assertEqual(export_response.status_code, 400)

    def test_invalid_or_reversed_date_filters_do_not_show_unfiltered_forms_or_export(self):
        template = self.create_date_filter_template()
        self.create_form_at(
            template,
            "existing-form",
            timezone.make_aware(datetime(2025, 1, 1, 12, 0), timezone.get_current_timezone()),
        )

        invalid_response = self.get_form_list(template, {"start": "not-a-date"})
        self.assertEqual(invalid_response.status_code, 200)
        self.assertFalse(invalid_response.context["page"].object_list)
        self.assertTrue(invalid_response.context["filter_form"].errors)

        reversed_params = {"start": "01/02/2025", "end": "01/01/2025"}
        reversed_response = self.get_form_list(template, reversed_params)
        self.assertEqual(reversed_response.status_code, 200)
        self.assertFalse(reversed_response.context["page"].object_list)
        self.assertTrue(reversed_response.context["filter_form"].errors)

        export_response = self.get_form_list(template, {**reversed_params, "csv": "true"})
        self.assertEqual(export_response.status_code, 400)

    def test_table_and_export_columns_validate_order_independently(self):
        template = CustomFormPDFTemplate.objects.create(
            name="Column order validation", form_fields='[{"name": "shared_field", "type": "text"}]'
        )
        CustomFormTableColumn.objects.create(
            template=template, field_name="shared_field", display_order=1, display_name="Table field"
        )
        export_column = CustomFormExportColumn(
            template=template, field_name="shared_field", display_order=1, display_name="Export field"
        )
        export_column.full_clean()
        export_column.save()

        with self.assertRaises(ValidationError):
            CustomFormTableColumn(
                template=template, field_name="shared_field", display_order=1, display_name="Duplicate table field"
            ).full_clean()
        with self.assertRaises(ValidationError):
            CustomFormExportColumn(
                template=template, field_name="shared_field", display_order=1, display_name="Duplicate export field"
            ).full_clean()

    def test_duplicate_template_copies_both_column_configurations(self):
        template = CustomFormPDFTemplate.objects.create(
            name="Template with columns", form_fields='[{"name": "shared_field", "type": "text"}]'
        )
        CustomFormTableColumn.objects.create(
            template=template, field_name="shared_field", display_order=1, display_name="Table field"
        )
        CustomFormExportColumn.objects.create(
            template=template, field_name="shared_field", display_order=1, display_name="Export field"
        )
        request = RequestFactory().post("/")
        request.__dict__["_messages"] = Mock()

        duplicate_custom_form_template(None, request, CustomFormPDFTemplate.objects.filter(pk=template.pk))

        template_copy = CustomFormPDFTemplate.objects.get(name="Copy of Template with columns")
        self.assertEqual(
            list(template_copy.customformtablecolumn_set.values_list("field_name", "display_name")),
            [("shared_field", "Table field")],
        )
        self.assertEqual(
            list(template_copy.customformexportcolumn_set.values_list("field_name", "display_name")),
            [("shared_field", "Export field")],
        )

    def test_next_custom_form_number(self):
        custom_form_template = CustomFormPDFTemplate.objects.create(name="Form 1", id=1)
        # Test easy cases, if auto numbering doesn't exist or is not enabled, shouldn't return anything
        self.assertFalse(custom_form_template.next_custom_form_number(self.user))
        automatic_numbering: CustomFormAutomaticNumbering = CustomFormAutomaticNumbering.objects.create(
            template=custom_form_template, enabled=False
        )
        self.assertFalse(custom_form_template.next_custom_form_number(self.user))
        # Enabled and simple template with current number
        automatic_numbering.enabled = True
        automatic_numbering.numbering_template = "{{ current_number }}"
        automatic_numbering.role = "is_staff"
        automatic_numbering.save()
        current_number = 1
        self.assertEqual(custom_form_template.next_custom_form_number(self.user, save=True), f"{current_number}")
        current_number += 1
        self.assertEqual(custom_form_template.next_custom_form_number(self.user), f"{current_number}")
        # Enabled and using group
        automatic_numbering.enabled = True
        automatic_numbering.numbering_group = 2024
        automatic_numbering.numbering_per_user = False
        automatic_numbering.numbering_template = "{{ current_number }}"
        automatic_numbering.save()
        # Group but no user
        # We are using the group, so it's a different count
        current_number_group = 1
        self.assertEqual(custom_form_template.next_custom_form_number(self.user), f"{current_number_group}")
        automatic_numbering.numbering_template = "{{ numbering_group }}-{{ current_number }}"
        automatic_numbering.save()
        self.assertEqual(
            custom_form_template.next_custom_form_number(self.user, save=True), f"2024-{current_number_group}"
        )
        current_number_group += 1
        self.assertEqual(custom_form_template.next_custom_form_number(self.user), f"2024-{current_number_group}")
        # User but no group
        # Let's now use the user, so it's a different count
        current_number_user = 1
        automatic_numbering.enabled = True
        automatic_numbering.numbering_per_user = True
        automatic_numbering.numbering_group = None
        automatic_numbering.numbering_template = "{{ current_number }}"
        automatic_numbering.save()
        self.assertEqual(custom_form_template.next_custom_form_number(self.user, save=True), f"{current_number_user}")
        current_number_user += 1
        automatic_numbering.numbering_template = "{{ numbering_group }}-{{ user.username }}-{{ current_number }}"
        automatic_numbering.save()
        self.assertEqual(
            custom_form_template.next_custom_form_number(self.user, save=True),
            f"-{self.user.username}-{current_number_user}",
        )
        # User and group
        # Let's now use both, so it's a different count again
        current_number_user_group = 1
        automatic_numbering.enabled = True
        automatic_numbering.numbering_per_user = True
        automatic_numbering.numbering_group = 24
        automatic_numbering.numbering_template = "{{ current_number }}"
        automatic_numbering.save()
        self.assertEqual(
            custom_form_template.next_custom_form_number(self.user, save=True), f"{current_number_user_group}"
        )
        current_number_user_group += 1
        automatic_numbering.numbering_template = "{{ numbering_group }}-{{ user.username }}-{{ current_number }}"
        automatic_numbering.save()
        self.assertEqual(
            custom_form_template.next_custom_form_number(self.user, save=True),
            f"24-{self.user.username}-{current_number_user_group}",
        )
        current_number_user_group += 1
        # Test with full numbering template: {numbering_group}-680-{FirstNameFirstLetter}{LastNameFirstLetter}{number with leading zeros}
        automatic_numbering.numbering_template = "{{ numbering_group }}-680-{{ user.first_name.0|capfirst }}{{ user.last_name.0|capfirst }}{{ current_number|stringformat:'03d' }}"
        automatic_numbering.save()
        self.assertEqual(custom_form_template.next_custom_form_number(self.user), f"24-680-TM003")
        # Change template and check number. it should have reset
        custom_form_template_2 = CustomFormPDFTemplate.objects.create(name="Form 2")
        self.assertFalse(custom_form_template_2.next_custom_form_number(self.user))

    def test_current_custom_form_order_numbers(self):
        # reset all custom form settings
        Customization.objects.filter(name__startswith=CUSTOM_FORM_CURRENT_NUMBER_PREFIX).delete()
        custom_form_template = CustomFormPDFTemplate.objects.create(name="Form 11", id=11)
        custom_form_template_2 = CustomFormPDFTemplate.objects.create(name="Form 12", id=12)
        automatic_numbering: CustomFormAutomaticNumbering = CustomFormAutomaticNumbering.objects.create(
            template=custom_form_template, enabled=False
        )
        automatic_numbering_2: CustomFormAutomaticNumbering = CustomFormAutomaticNumbering.objects.create(
            template=custom_form_template_2, enabled=False
        )
        # Case 1: automatic numbering enabled
        automatic_numbering.enabled = True
        automatic_numbering.numbering_per_user = False
        automatic_numbering.numbering_group = None
        automatic_numbering.numbering_template = "{{ current_number }}"
        automatic_numbering.role = "is_staff"
        automatic_numbering.full_clean()
        automatic_numbering.save()
        automatic_numbering.next_custom_form_number(self.user, save=True)
        self.assertEqual({None: "1"}, custom_forms_current_numbers(custom_form_template))
        # reset all custom form settings
        Customization.objects.filter(name__startswith=CUSTOM_FORM_CURRENT_NUMBER_PREFIX).delete()
        # Case 2: automatic numbering enabled, by user only
        automatic_numbering.enabled = True
        automatic_numbering.numbering_per_user = True
        automatic_numbering.numbering_group = None
        automatic_numbering.numbering_template = "{{ current_number }}"
        automatic_numbering.save()
        automatic_numbering.next_custom_form_number(self.user, save=True)
        self.assertEqual({str(self.user.id): "1"}, custom_forms_current_numbers(custom_form_template))
        # reset all custom form settings
        Customization.objects.filter(name__startswith=CUSTOM_FORM_CURRENT_NUMBER_PREFIX).delete()
        # Case 3: automatic numbering enabled, by group
        automatic_numbering.enabled = True
        automatic_numbering.numbering_per_user = False
        automatic_numbering.numbering_group = 24
        automatic_numbering.numbering_template = "{{ current_number }}"
        automatic_numbering.save()
        automatic_numbering.next_custom_form_number(self.user, save=True)
        self.assertEqual({"24": "1"}, custom_forms_current_numbers(custom_form_template))
        # reset all custom form settings
        Customization.objects.filter(name__startswith=CUSTOM_FORM_CURRENT_NUMBER_PREFIX).delete()
        # Case 4: automatic numbering enabled, by group and user
        automatic_numbering.enabled = True
        automatic_numbering.numbering_per_user = True
        automatic_numbering.numbering_group = 24
        automatic_numbering.numbering_template = "{{ current_number }}"
        automatic_numbering.save()
        automatic_numbering.next_custom_form_number(self.user, save=True)
        self.assertEqual({"24": {str(self.user.id): "1"}}, custom_forms_current_numbers(custom_form_template))
        # reset all custom form settings
        Customization.objects.filter(name__startswith=CUSTOM_FORM_CURRENT_NUMBER_PREFIX).delete()
        # Case 5: automatic numbering enabled, by group and user with 2 templates
        automatic_numbering.enabled = True
        automatic_numbering.numbering_per_user = True
        automatic_numbering.numbering_group = 24
        automatic_numbering.numbering_template = "{{ current_number }}"
        automatic_numbering.save()
        automatic_numbering_2.enabled = True
        automatic_numbering_2.numbering_per_user = True
        automatic_numbering_2.numbering_group = 24
        automatic_numbering_2.numbering_template = "{{ current_number }}"
        automatic_numbering_2.role = "is_staff"
        automatic_numbering_2.save()
        automatic_numbering.next_custom_form_number(self.user, save=True)
        automatic_numbering_2.next_custom_form_number(self.user, save=True)
        self.assertEqual({"24": {str(self.user.id): "1"}}, custom_forms_current_numbers(custom_form_template))
        self.assertEqual({"24": {str(self.user.id): "1"}}, custom_forms_current_numbers(custom_form_template_2))
        # reset all custom form settings
        Customization.objects.filter(name__startswith=CUSTOM_FORM_CURRENT_NUMBER_PREFIX).delete()
        # Case 6: automatic numbering enabled, by group and user with different groups
        automatic_numbering.enabled = True
        automatic_numbering.numbering_per_user = True
        automatic_numbering.numbering_group = 23
        automatic_numbering.numbering_template = "{{ current_number }}"
        automatic_numbering.save()
        automatic_numbering_2.enabled = True
        automatic_numbering_2.numbering_per_user = True
        automatic_numbering_2.numbering_group = 24
        automatic_numbering_2.numbering_template = "{{ current_number }}"
        automatic_numbering_2.save()
        automatic_numbering.next_custom_form_number(self.user, save=True),
        automatic_numbering_2.next_custom_form_number(self.user, save=True),
        self.assertEqual({"23": {str(self.user.id): "1"}}, custom_forms_current_numbers(custom_form_template))
        self.assertEqual({"24": {str(self.user.id): "1"}}, custom_forms_current_numbers(custom_form_template_2))
        # reset all custom form settings
        Customization.objects.filter(name__startswith=CUSTOM_FORM_CURRENT_NUMBER_PREFIX).delete()

    def test_action_role(self):
        custom_form_template = CustomFormPDFTemplate.objects.create(name="Form 11", id=11)
        action: CustomFormAction = CustomFormAction.objects.create(
            template=custom_form_template, rank=1, self_action_allowed=True
        )
        action.role = "is_staff"
        action.save()
        custom_form: CustomForm = CustomForm.objects.create(template=custom_form_template, creator=self.user)
        self.user.is_staff = False
        self.user.save()
        self.assertFalse(custom_form.can_take_next_action(self.user))
        self.assertNotIn(self.user, custom_form.next_action_candidates())
        self.staff_user, self.staff_project = create_user_and_project(is_staff=True)
        self.assertTrue(custom_form.can_take_next_action(self.staff_user))
        self.assertIn(self.staff_user, custom_form.next_action_candidates())
        new_group = Group.objects.create(name="New Group")
        action.role = new_group.id
        action.save()
        self.assertFalse(custom_form.can_take_next_action(self.staff_user))
        self.assertNotIn(self.staff_user, custom_form.next_action_candidates())
        self.user.groups.add(new_group)
        self.assertFalse(custom_form.can_take_next_action(self.staff_user))
        self.assertNotIn(self.staff_user, custom_form.next_action_candidates())
        self.assertTrue(custom_form.can_take_next_action(self.user))
        self.assertIn(self.user, custom_form.next_action_candidates())
        action.self_action_allowed = False
        action.save()
        self.assertFalse(custom_form.can_take_next_action(self.user))
        self.assertNotIn(self.user, custom_form.next_action_candidates())

    def test_next_custom_form_numbering_role(self):
        custom_form_template = CustomFormPDFTemplate.objects.create(name="Form 12", id=12)
        automatic_numbering = CustomFormAutomaticNumbering(template=custom_form_template)
        automatic_numbering.enabled = True
        automatic_numbering.numbering_per_user = False
        automatic_numbering.numbering_group = None
        automatic_numbering.numbering_template = "{{ current_number }}"
        automatic_numbering.role = "is_superuser"
        automatic_numbering.full_clean()
        automatic_numbering.save()
        self.assertFalse(automatic_numbering.next_custom_form_number(self.user))
        automatic_numbering.role = "is_staff"
        automatic_numbering.full_clean()
        automatic_numbering.save()
        self.assertTrue(automatic_numbering.next_custom_form_number(self.user))

    def test_custom_form_documents_is_allowed(self):
        creator, _ = create_user_and_project(is_staff=False)
        reviewer_staff, _ = create_user_and_project(is_staff=True)
        reviewer_group_user, _ = create_user_and_project(is_staff=False)
        unauthorized_user, _ = create_user_and_project(is_staff=False)

        reviewer_group = Group.objects.create(name="Reviewer Group")
        reviewer_group_user.groups.add(reviewer_group)

        custom_form_template = CustomFormPDFTemplate.objects.create(name="Document Template Test")
        custom_form = CustomForm.objects.create(template=custom_form_template, creator=creator)
        document = CustomFormDocuments.objects.create(custom_form=custom_form)

        # Before any actions/roles are configured on the template:
        # Creator is allowed to see the document, others are not
        self.assertTrue(document.is_allowed(creator))
        self.assertFalse(document.is_allowed(reviewer_staff))
        self.assertFalse(document.is_allowed(reviewer_group_user))
        self.assertFalse(document.is_allowed(unauthorized_user))

        # Add staff action
        action_staff = CustomFormAction.objects.create(template=custom_form_template, rank=1, role="is_staff")
        self.assertTrue(document.is_allowed(creator))
        self.assertTrue(document.is_allowed(reviewer_staff))
        self.assertFalse(document.is_allowed(reviewer_group_user))
        self.assertFalse(document.is_allowed(unauthorized_user))

        # Add group action
        action_group = CustomFormAction.objects.create(template=custom_form_template, rank=2, role=reviewer_group.id)
        self.assertTrue(document.is_allowed(creator))
        self.assertTrue(document.is_allowed(reviewer_staff))
        self.assertTrue(document.is_allowed(reviewer_group_user))
        self.assertFalse(document.is_allowed(unauthorized_user))

        # When group user is removed from reviewer group, they lose permission
        reviewer_group_user.groups.remove(reviewer_group)
        self.assertFalse(document.is_allowed(reviewer_group_user))

        # When staff user loses staff privileges, they lose permission
        reviewer_staff.is_staff = False
        reviewer_staff.save()
        self.assertFalse(document.is_allowed(reviewer_staff))

        # Creator remains allowed regardless
        self.assertTrue(document.is_allowed(creator))
