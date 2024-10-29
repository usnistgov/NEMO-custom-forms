# NEMO-custom-forms

[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/NEMO-custom-forms?label=python)](https://www.python.org/downloads/release/python-3110/)
[![PyPI](https://img.shields.io/pypi/v/nemo-custom-forms?label=pypi%20version)](https://pypi.org/project/NEMO-custom-forms/)
[![Changelog](https://img.shields.io/gitlab/v/release/gitlab/nanofab/nemo-custom-forms?include_prereleases&label=changelog)](https://gitlab.nist.gov/gitlab/nanofab/nemo-custom-forms/releases)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://gitlab.nist.gov/gitlab/nanofab/nemo-custom-forms/blob/main/LICENSE)

Plugin for NEMO allowing creation, rendering and approval of custom forms for users/staff

## Installation

```bash
python -m install nemo-custom-forms
```

in `settings.py` add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    '...',
    'NEMO_custom_forms',
    '...'
]
```

## Usage

Usage instructions go here.

# Tests

To run the tests:
```bash
python runtests.py
```
