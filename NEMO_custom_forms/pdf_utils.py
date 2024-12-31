from __future__ import annotations

import io
from io import BytesIO
from pathlib import Path
from typing import Dict, IO, KeysView, List, Optional, TYPE_CHECKING, Union

import requests
from PIL import Image, ImageDraw, ImageFont
from charset_normalizer.md import getLogger
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.exceptions import ValidationError
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.constants import (
    AnnotationDictionaryAttributes,
    CatalogDictionary,
    FieldDictionaryAttributes,
    InteractiveFormDictEntries,
    PageAttributes,
)
from pypdf.generic import NameObject, NumberObject, PdfObject

if TYPE_CHECKING:
    from NEMO_custom_forms.models import CustomFormDocuments


def validate_pdf_form(file):
    """
    Validates a PDF form by ensuring it is a valid PDF file and contains form fields.

    :param file: The file-like object representing the PDF to be validated.

    :raises ValidationError: If the file is not a supported PDF form or does not contain any form fields.
    """
    try:
        PdfReader(file, strict=True)
    except:
        raise ValidationError("Only PDF forms are supported.")
    fields = get_pdf_form_field_names(file)
    if not fields:
        raise ValidationError("Could not find any fields in the PDF form.")


def get_pdf_form_field_names(stream: Union[Union[str, IO], Path]) -> KeysView[str]:
    """
    Extracts and retrieves the form field names from a PDF document.

    :param stream: A file-like object, string, or Path providing access to the PDF document. The parameter may include
     a file path as a string, an input stream object, or a pathlib.Path object representing the PDF file.
    :return: A read-only view of the form field names, represented as strings, available in the PDF document.
    """
    return PdfReader(stream).get_fields().keys()


def get_pdf_form_field_states_for_field(stream: Union[Union[str, IO], Path], field_name) -> List[str]:
    """
    Extracts and returns all possible states for a given form field in a PDF.

    :param stream: The input PDF stream to be read. This can be a file path as a string, an IO object, or a Path object.
    :param field_name: The name of the form field for which states will be retrieved.
    :return: A list of strings representing the possible states of the specified form field in the PDF.
    """
    fields = PdfReader(stream).get_fields()
    states = fields.get(field_name).get("/_States_")
    return states


def flatten_pdf(writer: PdfWriter):
    """
    Flatten all form fields in a given PDF by setting them to read-only. This ensures
    that fields within the PDF cannot be modified, effectively making the document
    non-editable.

    :param writer: Instance of PdfWriter, representing the PDF document to be flattened.
    :type writer: PdfWriter
    """
    if CatalogDictionary.ACRO_FORM in writer.root_object:
        acro_form: Union[Dict, PdfObject] = writer.root_object[CatalogDictionary.ACRO_FORM]
        if InteractiveFormDictEntries.Fields in acro_form:
            for field in acro_form[InteractiveFormDictEntries.Fields]:
                field_dict = field.get_object()
                # Update the /Ff field to set the read-only flag
                if FieldDictionaryAttributes.Ff in field_dict:
                    # Perform a bitwise OR to enable the read-only flag
                    field_dict[NameObject(FieldDictionaryAttributes.Ff)] = NumberObject(
                        field_dict[FieldDictionaryAttributes.Ff] | FieldDictionaryAttributes.FfBits.ReadOnly
                    )
                else:
                    # Add the /Ff entry if it doesn't already exist
                    field_dict[NameObject(FieldDictionaryAttributes.Ff)] = NumberObject(
                        FieldDictionaryAttributes.FfBits.ReadOnly
                    )


def add_signature_mappings_to_pdf(writer: PdfWriter, signature_mappings: Dict):
    for page in writer.pages:
        if PageAttributes.ANNOTS in page:
            page_annotations: Union[Dict, PdfObject] = page[PageAttributes.ANNOTS]
            for field_name, field_value in signature_mappings.items():
                # For each annotation on the page, check for the field name
                for annotation in page_annotations:
                    annotation_object = annotation.get_object()
                    if field_value:
                        # Check if the field name matches
                        if (
                            annotation_object.get(FieldDictionaryAttributes.T) == field_name
                            or annotation_object.get(FieldDictionaryAttributes.TU) == field_name
                        ):
                            field_box = annotation_object.get(AnnotationDictionaryAttributes.Rect)
                            field_box_width = field_box[2] - field_box[0]
                            field_box_height = field_box[3] - field_box[1]
                            text_as_image = create_signature_image_from_name(
                                field_value, (field_box_width, field_box_height)
                            )
                            if text_as_image:
                                signature_pdf_page = convert_image_to_pdf_page(text_as_image)
                                signature_width = signature_pdf_page.mediabox[2] - signature_pdf_page.mediabox[0]
                                signature_height = signature_pdf_page.mediabox[3] - signature_pdf_page.mediabox[1]
                                horizontal_start = (field_box_width - signature_width) / 2
                                vertical_start = (field_box_height - signature_height) / 2
                                page.merge_transformed_page(
                                    signature_pdf_page,
                                    Transformation().translate(
                                        field_box[0] + horizontal_start, field_box[1] + vertical_start
                                    ),
                                )


def merge_documents(document_list: List[bytes | CustomFormDocuments]) -> Optional[bytes]:
    """
    Merges multiple PDF documents into a single PDF file. The input documents
    can either be in the form of bytes or instances of CustomFormDocuments
    retrieved from a URL. If an error occurs during the merging process for
    a specific document, it logs the exception and continues with the rest
    of the documents.

    :param document_list: A list of documents to be merged. Each element can
                          be either of type bytes or an instance of
                          CustomFormDocuments, which provides the document
                          content through a URL.
    :return: The merged PDF document as a byte string, or None if the
             merging process fails completely.
    """
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


def create_signature_image_from_name(user_name, within_box=(), max_font_size=48, padding=2, color="black") -> Image:
    """
    Generate a signature image from a given user name. This function uses a custom font to create a visually pleasing
    textual representation of the user's name as an image. The font size is dynamically adjusted to fit within the
    specified bounding box or maximum size, ensuring the resulting image fits prescribed constraints. Additionally,
    the image provides padding around the text for better visual appearance and uses a specified color.

    :param user_name: The text that will appear as the content of the signature image.
    :param within_box: An optional tuple consisting of (width, height) that defines the
        bounding box for the signature text. If not provided, no constraints on the box size are applied.
    :param max_font_size: The maximum font size to be used when rendering the signature. Defaults to 48.
    :param padding: The padding (in pixels) added around the signature text inside the bounding box. Defaults to 2.
    :param color: The color of the text in the signature image. Defaults to "black".
    :return: An image object containing the signature, or None if the text cannot fit within the specified constraints.
    """
    # TODO: allow customizing the signature font in settings.py
    signature_font_path = staticfiles_storage.path("NEMO_custom_forms/fonts/dancing_script.ttf")
    signature_font = ImageFont.truetype(signature_font_path, size=max_font_size)
    font_size = max_font_size
    dummy_img = Image.new("RGBA", (1, 1))  # Dummy image for text size calculation
    tmp_draw = ImageDraw.Draw(dummy_img)

    # Try smaller font size until it fits
    while True:
        text_bbox = tmp_draw.textbbox((0, 0), user_name, font=signature_font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        # Add padding around the text
        total_width = round(text_width) + (2 * padding)
        total_height = round(text_height) + (2 * padding)

        # Check if text fits within the given box (width, height) if we have a box
        if not within_box or (total_width <= within_box[0] and total_height <= within_box[1]):
            break

        # If text doesn't fit, reduce font size
        font_size -= 1
        if font_size < 1:  # Prevent infinite loop
            getLogger(__name__).warning(
                f"Text: '{user_name}' cannot fit within the given box, even at the smallest font size, skipping"
            )
            return None
        signature_font = ImageFont.truetype(signature_font_path, size=font_size)

    # Create an image just large enough to fit the text
    signature_img = Image.new("RGBA", (total_width, total_height), (255, 255, 255, 0))  # Transparent background
    # Draw the text onto the image
    draw = ImageDraw.Draw(signature_img)
    draw.text((padding, -padding), user_name, fill=color, font=signature_font)

    return signature_img


def convert_image_to_pdf_page(image: Image):
    """
    Converts an image into a single-page PDF and extracts that page into a PDF page object.

    :param image: The image object to be converted to a PDF page.
    :return: The extracted single PDF page object created from the input image.
    """
    img_byte_stream = io.BytesIO()
    image.save(img_byte_stream, format="PDF")
    img_byte_stream.seek(0)

    tmp_reader = PdfReader(img_byte_stream)
    pdf_page = tmp_reader.pages[0]  # Extract the only page

    return pdf_page


def clone_pdf(stream: Union[Union[str, IO], Path]) -> PdfWriter:
    """
    Creates a complete copy of a PDF document from the given input stream or file path.

    :param stream: The input source for the PDF to be cloned. Can be provided as a string representing the file path,
    an IO object for binary reading, or a Path object representing the file system path to the target document.
    :return: A PdfWriter object containing the cloned PDF document.
    """
    reader = PdfReader(stream)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    return writer


def copy_and_fill_pdf_form(stream, field_key_values: Dict, signature_mappings: Dict, flatten=True) -> bytes:
    """
    Copies and fills a given PDF form with specified field key-value pairs and optional signature mappings. Allows
    optionally flattening the PDF after updating the form fields. The filled PDF is returned as a bytes object.

    :param stream: A file-like object representing the input PDF to be copied and filled.
    :param field_key_values: A dictionary containing the field names as keys and their corresponding values to populate
    in the PDF form.
    :param signature_mappings: A dictionary mapping signature fields to their respective signature data.
    :param flatten: A boolean indicating whether to flatten the PDF form fields after filling them. Defaults to True.
    :return: A bytes object containing the updated and optionally flattened PDF content.
    """
    writer = clone_pdf(stream)

    for page in writer.pages:
        writer.update_page_form_field_values(writer.pages[page.page_number], field_key_values)

    if flatten:
        flatten_pdf(writer)

    if signature_mappings:
        add_signature_mappings_to_pdf(writer, signature_mappings)

    with BytesIO() as buffer:
        writer.write(buffer)
        return buffer.getvalue()
