from __future__ import annotations

import io
from io import BytesIO
from pathlib import Path
from typing import Dict, IO, KeysView, List, Optional, TYPE_CHECKING, Union

import requests
from charset_normalizer.md import getLogger
from django.core.exceptions import ValidationError
from pypdf import PdfReader, PdfWriter

if TYPE_CHECKING:
    from NEMO_custom_forms.models import CustomFormDocuments


def validate_is_pdf_form(file):
    try:
        PdfReader(file, strict=True)
    except:
        raise ValidationError("Only PDF forms are supported.")
    fields = pdf_form_field_names(file)
    if not fields:
        raise ValidationError("Could not find any fields in the PDF form.")


def pdf_form_field_names(stream: Union[Union[str, IO], Path]) -> KeysView[str]:
    return PdfReader(stream).get_fields().keys()


def pdf_form_field_states_for_field(stream: Union[Union[str, IO], Path], field_name) -> List[str]:
    fields = PdfReader(stream).get_fields()
    states = fields.get(field_name).get("/_States_")
    return states


def copy_pdf(stream: Union[Union[str, IO], Path]) -> PdfWriter:
    reader = PdfReader(stream)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    return writer


def copy_and_fill_pdf_form(stream: Union[Union[str, IO], Path], field_key_values: Dict) -> bytes:
    writer = copy_pdf(stream)

    for page in writer.pages:
        writer.update_page_form_field_values(writer.pages[page.page_number], field_key_values)

    with BytesIO() as buffer:
        writer.write(buffer)
        return buffer.getvalue()


def merge_documents(document_list: List[bytes | CustomFormDocuments]) -> Optional[bytes]:
    merger = PdfWriter()

    for document in document_list:
        try:
            if isinstance(document, bytes):
                doc_bytes = document
            else:
                doc_bytes = get_bytes_from_url_document(document.full_link())
            with BytesIO(doc_bytes) as byte_stream:
                pdf_file = PdfReader(byte_stream)
                merger.append(pdf_file)
        except:
            getLogger(__name__).exception("Error opening or merging document")

    with io.BytesIO() as byte_stream:
        merger.write(byte_stream)
        return byte_stream.getvalue()


def get_bytes_from_url_document(document_url) -> bytes:
    response = requests.get(document_url)
    response.raise_for_status()
    return response.content
