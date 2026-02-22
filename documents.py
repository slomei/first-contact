"""
PDF document generation for the chatbot.

Imports memory (base module). No circular dependencies.
"""

import os
import re
from datetime import datetime

try:
    from reportlab.lib.pagesizes import letter as _letter_size
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor, black, gray
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    )
    _REPORTLAB_AVAILABLE = True
except ImportError:
    _REPORTLAB_AVAILABLE = False
    _letter_size = (612, 792)
    inch = 72
    HexColor = black = gray = None
    ParagraphStyle = SimpleDocTemplate = Paragraph = Spacer = HRFlowable = None

import memory

# --- Constants ---

ACCENT_COLOR = HexColor("#145545") if HexColor else None
HEADER_GRAY = HexColor("#666666") if HexColor else None

PAGE_WIDTH, PAGE_HEIGHT = _letter_size  # 612 x 792 points

def _load_contact():
    """Load contact info from config (matches resume)."""
    config = memory.load_config()
    profile = config.get("user_profile", {})
    return {
        "name": profile.get("name", "Your Name"),
        "email": profile.get("email", ""),
        "phone": profile.get("phone", ""),
        "website": profile.get("website", ""),
        "location": profile.get("location", ""),
    }

# Cover letter output directory
COVER_LETTER_DIR = os.path.join(
    memory.PROJECTS_DIR, memory.JOB_SEARCH_PROJECT, "workspace", "cover_letters"
)


# --- Styles ---

def _base_styles(body_font_size=11, body_space_after=10):
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
            fontSize=body_font_size,
            leading=body_font_size + 4,
            textColor=black,
        ),
        "recipient": ParagraphStyle(
            "Recipient",
            fontName="Helvetica",
            fontSize=body_font_size,
            leading=body_font_size + 4,
            textColor=black,
        ),
        "body": ParagraphStyle(
            "Body",
            fontName="Helvetica",
            fontSize=body_font_size,
            leading=body_font_size * 1.4,
            textColor=black,
            spaceAfter=body_space_after,
        ),
        "signature": ParagraphStyle(
            "Signature",
            fontName="Helvetica",
            fontSize=body_font_size,
            leading=body_font_size + 4,
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

def _build_cover_story(recipient_name, company_name, job_title, paragraphs,
                       body_font_size=11, body_space_after=10):
    """Build the platypus story list for a cover letter.

    Returns (story, styles) so the caller can measure or build.
    """
    contact = _load_contact()
    styles = _base_styles(body_font_size, body_space_after)
    story = []

    # Header: name
    story.append(Paragraph(contact["name"], styles["name"]))
    story.append(Spacer(1, 2))

    # Header: contact info line
    parts = [p for p in [contact["location"], contact["phone"],
                         contact["email"], contact["website"]] if p]
    contact_line = "  &bull;  ".join(parts)
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
    for para in paragraphs:
        safe = _escape_xml(para)
        story.append(Paragraph(safe, styles["body"]))

    # Signature — tight spacing
    story.append(Spacer(1, 10))
    story.append(Paragraph("Sincerely,", styles["signature"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(contact["name"], styles["signature"]))

    return story, styles


def _measure_story(story, avail_width, avail_height):
    """Measure total height of a story. Returns height in points."""
    total = 0
    for flowable in story:
        w, h = flowable.wrap(avail_width, avail_height)
        total += h
        # Account for spaceAfter/spaceBefore on flowables that have it
        total += getattr(flowable, 'spaceAfter', 0)
        total += getattr(flowable, 'spaceBefore', 0)
    return total


def generate_cover_letter_pdf(
    recipient_name,
    company_name,
    job_title,
    cover_letter_text,
    output_path=None,
):
    """Generate a professional one-page cover letter PDF.

    Automatically adjusts spacing, margins, and font size to fit one page.
    As a last resort, asks Opus to shorten the letter.

    Args:
        recipient_name: Name of recipient (e.g. "Hiring Manager")
        company_name: Company name
        job_title: Position title
        cover_letter_text: Full cover letter body text
        output_path: Where to save. If None, auto-generates in COVER_LETTER_DIR.

    Returns:
        The output file path.
    """
    if not _REPORTLAB_AVAILABLE:
        # Fallback: save as plain text file
        if output_path is None:
            os.makedirs(COVER_LETTER_DIR, exist_ok=True)
            slug = re.sub(r'[^\w]+', '_', f"{company_name}_{job_title}").strip('_')
            output_path = os.path.join(COVER_LETTER_DIR, f"{slug}_cover.txt")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(f"Cover Letter — {job_title} at {company_name}\n\n")
            f.write(f"Dear {recipient_name},\n\n")
            f.write(cover_letter_text)
        return output_path

    if output_path is None:
        os.makedirs(COVER_LETTER_DIR, exist_ok=True)
        slug = re.sub(r'[^\w]+', '_', f"{company_name}_{job_title}").strip('_')
        output_path = os.path.join(COVER_LETTER_DIR, f"{slug}_cover.pdf")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    paragraphs = _split_paragraphs(cover_letter_text)

    # Try progressively tighter settings to fit one page
    #   (margin_inches, body_font_size, body_space_after)
    fit_attempts = [
        (1.0,  11, 10),   # default
        (1.0,  11,  6),   # tighter paragraph spacing
        (1.0,  11,  3),   # minimal paragraph spacing
        (0.85, 11,  3),   # smaller margins
        (0.75, 11,  3),   # minimum margins
        (0.75, 10.5, 2),  # slightly smaller font
        (0.75, 10,  2),   # minimum font
    ]

    chosen_margin = 1.0
    chosen_font = 11
    chosen_space = 10
    fits = False

    for margin, font_size, space_after in fit_attempts:
        story, styles = _build_cover_story(
            recipient_name, company_name, job_title, paragraphs,
            body_font_size=font_size, body_space_after=space_after,
        )
        avail_w = PAGE_WIDTH - 2 * margin * inch
        avail_h = PAGE_HEIGHT - 2 * margin * inch
        height = _measure_story(story, avail_w, avail_h)

        if height <= avail_h:
            chosen_margin = margin
            chosen_font = font_size
            chosen_space = space_after
            fits = True
            break

    # Last resort: ask Opus to shorten
    if not fits:
        cover_letter_text = _shorten_with_opus(cover_letter_text)
        paragraphs = _split_paragraphs(cover_letter_text)
        chosen_margin = 0.75
        chosen_font = 10
        chosen_space = 2

    # Build final PDF
    story, styles = _build_cover_story(
        recipient_name, company_name, job_title, paragraphs,
        body_font_size=chosen_font, body_space_after=chosen_space,
    )

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=chosen_margin * inch,
        rightMargin=chosen_margin * inch,
        topMargin=chosen_margin * inch,
        bottomMargin=chosen_margin * inch,
    )

    doc.build(story)
    return output_path


def _shorten_with_opus(text):
    """Ask Opus to tighten a cover letter to fit one page."""
    import models
    try:
        response = models.get_client().messages.create(
            model="claude-opus-4-6",
            max_tokens=800,
            messages=[{"role": "user", "content":
                "This cover letter is too long for one page. Tighten it to fit "
                "while keeping all key points and specific details. Remove filler "
                "and condense, but keep the professional tone and specific project "
                "references. Do NOT add a greeting or signature — just the body "
                "paragraphs.\n\n" + text}],
        )
        models.track_usage(response.usage.input_tokens,
                           response.usage.output_tokens,
                           "claude-opus-4-6")
        return response.content[0].text
    except Exception:
        # If API fails, just truncate to first 4 paragraphs
        paras = text.strip().split("\n\n")
        return "\n\n".join(paras[:4])


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
    if not _REPORTLAB_AVAILABLE:
        # Fallback: save as plain text
        txt_path = output_path.rsplit(".", 1)[0] + ".txt"
        os.makedirs(os.path.dirname(txt_path), exist_ok=True)
        with open(txt_path, "w") as f:
            f.write(f"{title}\n{'=' * len(title)}\n\n{body_text}")
        return txt_path

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    styles = _base_styles()

    doc = SimpleDocTemplate(
        output_path,
        pagesize=_letter_size,
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
    # Remove trailing name line (matches the user's name from config)
    contact = _load_contact()
    name_parts = contact["name"].split()
    if name_parts:
        name_pattern = "|".join(re.escape(p) for p in name_parts)
        while lines and re.match(
            rf'^({name_pattern})',
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
