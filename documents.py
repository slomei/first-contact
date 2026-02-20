"""
PDF document generation for the chatbot.

Imports memory (base module). No circular dependencies.
"""

import os
import re
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black, gray
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
)
from reportlab.lib.enums import TA_LEFT

import memory

# --- Constants ---

ACCENT_COLOR = HexColor("#145545")
HEADER_GRAY = HexColor("#666666")

# Contact info (matches resume)
CONTACT = {
    "name": "Stephen M. Lomei",
    "email": "you@example.com",
    "phone": "000-000-0000",
    "website": "example.com",
    "location": "Yonkers, NY",
}

# Cover letter output directory
COVER_LETTER_DIR = os.path.join(
    memory.PROJECTS_DIR, memory.JOB_SEARCH_PROJECT, "workspace", "cover_letters"
)


# --- Styles ---

def _base_styles():
    """Return a dict of ParagraphStyles for cover letter PDFs."""
    return {
        "name": ParagraphStyle(
            "Name",
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=ACCENT_COLOR,
        ),
        "contact": ParagraphStyle(
            "Contact",
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=HEADER_GRAY,
        ),
        "date": ParagraphStyle(
            "Date",
            fontName="Helvetica",
            fontSize=11,
            leading=15,
            textColor=black,
        ),
        "recipient": ParagraphStyle(
            "Recipient",
            fontName="Helvetica",
            fontSize=11,
            leading=15,
            textColor=black,
        ),
        "body": ParagraphStyle(
            "Body",
            fontName="Helvetica",
            fontSize=11,
            leading=15.4,  # 1.4x line spacing
            textColor=black,
            spaceAfter=10,
        ),
        "signature": ParagraphStyle(
            "Signature",
            fontName="Helvetica",
            fontSize=11,
            leading=15,
            textColor=black,
        ),
        "title": ParagraphStyle(
            "DocTitle",
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=ACCENT_COLOR,
            spaceAfter=12,
        ),
    }


# --- Cover Letter PDF ---

def generate_cover_letter_pdf(
    recipient_name,
    company_name,
    job_title,
    cover_letter_text,
    output_path=None,
):
    """Generate a professional cover letter PDF.

    Args:
        recipient_name: Name of recipient (e.g. "Hiring Manager")
        company_name: Company name
        job_title: Position title
        cover_letter_text: Full cover letter body text
        output_path: Where to save. If None, auto-generates in COVER_LETTER_DIR.

    Returns:
        The output file path.
    """
    if output_path is None:
        os.makedirs(COVER_LETTER_DIR, exist_ok=True)
        slug = re.sub(r'[^\w]+', '_', f"{company_name}_{job_title}").strip('_')
        output_path = os.path.join(COVER_LETTER_DIR, f"{slug}_cover.pdf")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    styles = _base_styles()

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
    )

    story = []

    # Header: name
    story.append(Paragraph(CONTACT["name"], styles["name"]))
    story.append(Spacer(1, 2))

    # Header: contact info line
    contact_line = (
        f'{CONTACT["location"]}  &bull;  {CONTACT["phone"]}  &bull;  '
        f'{CONTACT["email"]}  &bull;  {CONTACT["website"]}'
    )
    story.append(Paragraph(contact_line, styles["contact"]))
    story.append(Spacer(1, 8))

    # Teal divider
    story.append(HRFlowable(
        width="100%", thickness=1.5, color=ACCENT_COLOR,
        spaceAfter=16, spaceBefore=0,
    ))

    # Date
    date_str = datetime.now().strftime("%B %d, %Y")
    story.append(Paragraph(date_str, styles["date"]))
    story.append(Spacer(1, 12))

    # Recipient block
    story.append(Paragraph(recipient_name, styles["recipient"]))
    story.append(Paragraph(company_name, styles["recipient"]))
    story.append(Spacer(1, 6))

    re_line = f"Re: {job_title}"
    story.append(Paragraph(f"<b>{re_line}</b>", styles["recipient"]))
    story.append(Spacer(1, 16))

    # Body paragraphs
    paragraphs = _split_paragraphs(cover_letter_text)
    for para in paragraphs:
        # Escape XML entities for reportlab
        safe = _escape_xml(para)
        story.append(Paragraph(safe, styles["body"]))

    # Signature
    story.append(Spacer(1, 12))
    story.append(Paragraph("Sincerely,", styles["signature"]))
    story.append(Spacer(1, 20))
    story.append(Paragraph(CONTACT["name"], styles["signature"]))

    doc.build(story)
    return output_path


# --- Generic PDF ---

def generate_pdf(title, body_text, output_path):
    """Generate a simple formatted PDF document.

    Args:
        title: Document title (displayed as header)
        body_text: Body text content
        output_path: Where to save the PDF

    Returns:
        The output file path.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    styles = _base_styles()

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
    )

    story = []

    # Title
    story.append(Paragraph(_escape_xml(title), styles["title"]))
    story.append(Spacer(1, 4))

    # Teal divider
    story.append(HRFlowable(
        width="100%", thickness=1, color=ACCENT_COLOR,
        spaceAfter=16, spaceBefore=0,
    ))

    # Date
    date_str = datetime.now().strftime("%B %d, %Y")
    story.append(Paragraph(date_str, styles["date"]))
    story.append(Spacer(1, 12))

    # Body paragraphs
    paragraphs = _split_paragraphs(body_text)
    for para in paragraphs:
        safe = _escape_xml(para)
        story.append(Paragraph(safe, styles["body"]))

    doc.build(story)
    return output_path


# --- Helpers ---

def _split_paragraphs(text):
    """Split text into paragraphs, preserving intentional breaks."""
    # Strip any leading "Dear..." / "Sincerely" wrapper if the LLM included them
    # (the PDF template adds its own header/signature)
    lines = text.strip().splitlines()

    # Remove greeting lines like "Dear Hiring Manager," at the start
    while lines and re.match(r'^(Dear\s|To\s)', lines[0], re.IGNORECASE):
        lines.pop(0)
        # Also remove blank line after greeting
        if lines and not lines[0].strip():
            lines.pop(0)

    # Remove signature lines at the end
    while lines and re.match(
        r'^(sincerely|regards|best|thank you|yours|warm)',
        lines[-1].strip(), re.IGNORECASE
    ):
        lines.pop()
    # Remove trailing name line (matches "Stephen", "Steve", or "Stephen M. Lomei")
    while lines and re.match(
        r'^(stephen|steve)',
        lines[-1].strip(), re.IGNORECASE
    ):
        lines.pop()
    # Remove trailing blank lines
    while lines and not lines[-1].strip():
        lines.pop()

    text = "\n".join(lines)

    # Split on double newlines (paragraph breaks)
    raw_paragraphs = re.split(r'\n\s*\n', text)
    paragraphs = []
    for p in raw_paragraphs:
        cleaned = p.strip()
        if cleaned:
            # Collapse single newlines within a paragraph to spaces
            cleaned = re.sub(r'\n', ' ', cleaned)
            paragraphs.append(cleaned)

    return paragraphs


def _escape_xml(text):
    """Escape text for reportlab Paragraph (XML-based)."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def slugify_job(company, title):
    """Create a filename slug from company and title."""
    raw = f"{company}_{title}"
    return re.sub(r'[^\w]+', '_', raw).strip('_')
