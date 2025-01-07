from NEMO.models import Customization
from NEMO.tests.test_utilities import create_user_and_project
from django.apps import apps
from django.contrib.auth.models import Group
from django.test import TestCase

from NEMO_custom_forms.models import (
    CustomForm,
    CustomFormAction,
    CustomFormAutomaticNumbering,
    CustomFormPDFTemplate,
)
from NEMO_custom_forms.utilities import CUSTOM_FORM_CURRENT_NUMBER_PREFIX, custom_forms_current_numbers


class CustomFormsTest(TestCase):

    def test_plugin_is_installed(self):
        assert apps.is_installed("NEMO_custom_forms")

    def setUp(self):
        self.user, self.project = create_user_and_project(is_staff=True)

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
