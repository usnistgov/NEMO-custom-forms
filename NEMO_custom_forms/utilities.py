from collections import defaultdict


def default_dict_to_regular_dict(d):
    if isinstance(d, defaultdict):
        d = {k: default_dict_to_regular_dict(v) for k, v in d.items()}
    return d
