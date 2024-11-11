from __future__ import annotations

import re
from collections import defaultdict
from logging import getLogger
from typing import Any, Dict, List, TYPE_CHECKING, Tuple

from NEMO.decorators import customization
from NEMO.models import Customization, User
from NEMO.utilities import quiet_int, slugify_underscore
from NEMO.views.customization import CustomizationBase
from django.core.exceptions import ValidationError
from django.template import Context, Template

from NEMO_custom_forms.utilities import default_dict_to_regular_dict

if TYPE_CHECKING:
    from NEMO_custom_forms.models import CustomForm, CustomFormPDFTemplate

cc_customization_logger = getLogger(__name__)


@customization(title="Custom forms", key="custom_forms")
class CustomFormCustomization(CustomizationBase):
    variables = {
        "custom_forms_view_staff": "",
        "custom_forms_view_user_office": "",
        "custom_forms_view_accounting_officer": "",
        "custom_forms_create_staff": "",
        "custom_forms_create_user_office": "",
        "custom_forms_create_accounting_officer": "",
        "custom_forms_self_approval_allowed": "",
        "custom_forms_number_template_enabled": "",
        "custom_forms_number_template_template": "enabled",
        "custom_forms_number_template_year": "",
        "custom_forms_number_template_user": "",
        "custom_forms_number_template": "{{ current_number|stringformat:'03d' }}",
    }

    def context(self) -> Dict:
        dictionary = super().context()
        dictionary["current_numbers"] = self.all_custom_forms_current_numbers()
        return dictionary

    def validate(self, name, value):
        if name == "custom_forms_number_template" and value:
            try:
                fake_user = User(first_name="Testy", last_name="McTester", email="testy_mctester@gmail.com")
                fake_template = CustomFormPDFTemplate(name="Test", id=1)
                self.next_custom_form_number(fake_user, fake_template, save=False)
            except Exception as e:
                raise ValidationError(str(e))

    @classmethod
    def all_custom_forms_current_numbers(cls) -> Dict:
        form_dict_list = [
            (split_form_patterns(f.name), f.value)
            for f in Customization.objects.filter(name__startswith="custom_form_current_number")
            if split_form_patterns(f.name)
        ]
        return merge_form_dicts(form_dict_list)

    @classmethod
    def next_custom_form_number(
        cls,
        user: User,
        custom_form_template: CustomFormPDFTemplate,
        custom_form: CustomForm = None,
        save=False,
    ) -> str:
        if CustomFormCustomization.get_bool("custom_forms_number_template_enabled"):
            form_number_template_current_year = CustomFormCustomization.get_int("custom_forms_number_template_year")
            form_number_template = CustomFormCustomization.get("custom_forms_number_template")
            form_number_by_user = CustomFormCustomization.get_bool("custom_forms_number_template_user")
            form_number_by_template = CustomFormCustomization.get_bool("custom_forms_number_template_template")
            current_number_customization = "custom_form_current_number"
            if form_number_by_template:
                current_number_customization += f"_t({slugify_underscore(custom_form_template.name)})"
            if form_number_template_current_year:
                current_number_customization += f"_y({slugify_underscore(form_number_template_current_year)})"
            if form_number_by_user:
                current_number_customization += f"_u({slugify_underscore(user.username)})"
            current_number = Customization.objects.filter(name=current_number_customization).first()
            current_number_value = quiet_int(current_number.value, 0) if current_number else 0
            current_number_value += 1
            context = {
                "custom_form_template": custom_form_template,
                "custom_form": custom_form,
                "user": user,
                "current_year": form_number_template_current_year or "",
                "current_number": current_number_value,
            }
            if save:
                try:
                    Customization(name=current_number_customization, value=current_number_value).save()
                except:
                    cc_customization_logger.exception("Error saving custom form current number")
            form_number = Template(form_number_template).render(Context(context))
            return form_number


def split_form_patterns(pattern: str):
    # Here we want to split patterns by template, year, and user if any of them are enabled
    result = {}
    re_pattern = "number"
    by_template = CustomFormCustomization.get_bool("custom_forms_number_template_template")
    by_year = bool(CustomFormCustomization.get_int("custom_forms_number_template_year"))
    by_user = CustomFormCustomization.get_bool("custom_forms_number_template_user")
    if not any([by_template, by_year, by_user]):
        return {None: None}  # special case so it's not skipped later
    if by_template:
        re_pattern += "_t\((.*?)\)"
    if by_year:
        re_pattern += "_y\((.*?)\)"
    if by_user:
        re_pattern += "_u\((.*?)\)"
    if re_pattern:
        pattern_regex = re.compile(r"{}".format(re_pattern))
        match = pattern_regex.search(pattern)
        if match:
            if by_template:
                result.update({"template": match.group(1)})
            if by_year:
                result.update({"year": match.group(2 if by_template else 1)})
            if by_user:
                result.update(
                    {"user": match.group(3 if by_template and by_year else 1 if not by_template and not by_year else 2)}
                )
    return result


def merge_form_dicts(dict_value_tuples: List[Tuple[dict, Any]]):
    by_template = CustomFormCustomization.get_bool("custom_forms_number_template_template")
    by_year = bool(CustomFormCustomization.get_int("custom_forms_number_template_year"))
    by_user = CustomFormCustomization.get_bool("custom_forms_number_template_user")
    number_of_options = sum([by_template, by_year, by_user])
    merged_dict = {}
    if number_of_options == 2:
        merged_dict = defaultdict(lambda: {})
    if number_of_options == 3:
        merged_dict = defaultdict(lambda: defaultdict(lambda: {}))
    for dict_match, current_value in dict_value_tuples:
        template, year, user = dict_match.get("template"), dict_match.get("year"), dict_match.get("user")
        if template:
            if year and user:
                merged_dict[template][year][user] = current_value
            elif year:
                merged_dict[template][year] = current_value
            elif user:
                merged_dict[template][user] = current_value
            else:
                merged_dict[template] = current_value
        elif year:
            if user:
                merged_dict[year][user] = current_value
            else:
                merged_dict[year] = current_value
        elif user:
            merged_dict[user] = current_value
        else:
            merged_dict[None] = current_value

    # Convert defaultdict to a regular dict for the final result
    return default_dict_to_regular_dict(merged_dict)
