"""
HTML to PDF Converter Module
Converts HTML files from Google Drive to PDF format.
"""

import io
from pyhtml2pdf import converter


def convert_html_to_pdf(html_file, output_filename):
    """
    Converts HTML content to PDF format.

    Args:
        html_file: File-like object (BytesIO) containing HTML data
        output_filename: Name for the output PDF file (without .pdf extension)

    Returns:
        bytes: PDF file content as bytes
    """
    # Read HTML content
    html_content = html_file.read()

    # Decode if bytes
    if isinstance(html_content, bytes):
        html_content = html_content.decode('utf-8')

    # Create output buffer
    output_buffer = io.BytesIO()

    # Convert HTML to PDF
    converter.convert(html_content, output_buffer)

    # Get the PDF bytes
    pdf_bytes = output_buffer.getvalue()
    output_buffer.close()

    return pdf_bytes
