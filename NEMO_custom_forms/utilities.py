from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, TYPE_CHECKING, Tuple

from NEMO_custom_forms.apps import CustomFormsConfig

if TYPE_CHECKING:
    from NEMO_custom_forms.models import CustomFormAutomaticNumbering, CustomFormPDFTemplate

CUSTOM_FORM_CURRENT_NUMBER_PREFIX = "custom_form_current_number"
CUSTOM_FORM_TEMPLATE_PREFIX = "t#"
CUSTOM_FORM_GROUP_PREFIX = "g#"
CUSTOM_FORM_USER_PREFIX = "u#"

CUSTOM_FORM_NOTIFICATION = "customform"
CUSTOM_FORM_EMAIL_CATEGORY = CustomFormsConfig.plugin_id + 1


def default_dict_to_regular_dict(d):
    if isinstance(d, defaultdict):
        d = {k: default_dict_to_regular_dict(v) for k, v in d.items()}
    return d


def custom_forms_current_numbers(form_template: CustomFormPDFTemplate) -> Dict:
    automatic_numbering: CustomFormAutomaticNumbering = getattr(form_template, "customformautomaticnumbering", None)
    if not automatic_numbering or not automatic_numbering.enabled:
        return {}

    from NEMO.models import Customization

    form_dict_list = [
        (split_form_patterns(f.name, automatic_numbering), f.value)
        for f in Customization.objects.filter(name__startswith=CUSTOM_FORM_CURRENT_NUMBER_PREFIX)
        if split_form_patterns(f.name, automatic_numbering)
    ]
    return merge_form_dicts(form_dict_list, automatic_numbering)


def split_form_patterns(pattern: str, automatic_numbering: CustomFormAutomaticNumbering):
    # Here we want to split patterns by group and user if any of them are enabled
    result = {}
    re_pattern = CUSTOM_FORM_CURRENT_NUMBER_PREFIX
    if not automatic_numbering.numbering_group and not automatic_numbering.numbering_per_user:
        return {None: None}  # special case so it's not skipped later
    re_pattern += f"_{CUSTOM_FORM_TEMPLATE_PREFIX}{automatic_numbering.template.id}"
    if automatic_numbering.numbering_group:
        re_pattern += f"_{CUSTOM_FORM_GROUP_PREFIX}(\\d+)"
    if automatic_numbering.numbering_per_user:
        re_pattern += f"_{CUSTOM_FORM_USER_PREFIX}(\\d+)"
    if re_pattern:
        pattern_regex = re.compile(re_pattern)
        match = pattern_regex.search(pattern)
        if match:
            if automatic_numbering.numbering_group:
                result.update({"group": match.group(1)})
            if automatic_numbering.numbering_per_user:
                result.update({"user": match.group(2 if automatic_numbering.numbering_group else 1)})
    return result


def merge_form_dicts(dict_value_tuples: List[Tuple[dict, Any]], automatic_numbering):
    merged_dict = {}
    if not automatic_numbering.numbering_group and not automatic_numbering.numbering_per_user:
        pass
    elif not automatic_numbering.numbering_group or not automatic_numbering.numbering_per_user:
        merged_dict = defaultdict(lambda: {})
    else:
        merged_dict = defaultdict(lambda: defaultdict(lambda: {}))
    for dict_match, current_value in dict_value_tuples:
        group, user = dict_match.get("group"), dict_match.get("user")
        if group and user:
            merged_dict[group][user] = current_value
        elif group:
            merged_dict[group] = current_value
        elif user:
            merged_dict[user] = current_value
        else:
            merged_dict[None] = current_value

    # Convert defaultdict to a regular dict for the final result
    return default_dict_to_regular_dict(merged_dict)
