"""Certificate code generation and PDF rendering (AJIET Certificate of Participation)."""

import os
import secrets
from io import BytesIO

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

import departments

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKGROUND = os.path.join(BASE_DIR, "static", "img", "certificate_bg.jpg")
FONT_REGULAR = os.path.join(BASE_DIR, "static", "fonts", "DejaVuSerif.ttf")
FONT_BOLD = os.path.join(BASE_DIR, "static", "fonts", "DejaVuSerif-Bold.ttf")

# Same page size as the original design (1600 x 1131 px picture at 0.75 pt per px).
PAGE_W, PAGE_H = 1200, 848

MAROON = HexColor("#813646")      # matches "Certificate of Participation"
INK = HexColor("#1F2A3C")
GOLD = HexColor("#F0D56A")        # the thin line above each signature name
COLLEGE_LINE = "A J Institute of Engineering &amp; Technology, Mangaluru"

# Same page size as the original design (1600 x 1131 px picture at 0.75 pt per px).
PAGE_W, PAGE_H = 1200, 848

MAROON = HexColor("#813646")      # matches "Certificate of Participation"
INK = HexColor("#1F2A3C")
ORGANIZER = "the Department of MCA, A J Institute of Engineering &amp; Technology, Mangaluru"


def _fonts():
    """Use the bundled serif fonts; fall back to built-in Times if they are missing."""
    if os.path.exists(FONT_REGULAR) and os.path.exists(FONT_BOLD):
        if "CertSerif" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("CertSerif", FONT_REGULAR))
            pdfmetrics.registerFont(TTFont("CertSerif-Bold", FONT_BOLD))
            registerFontFamily("CertSerif", normal="CertSerif", bold="CertSerif-Bold",
                               italic="CertSerif", boldItalic="CertSerif-Bold")
        return "CertSerif", "CertSerif-Bold"
    return "Times-Roman", "Times-Bold"


def new_certificate_code(event_id, student_id):
    """A short code printed on the PDF so a certificate can be checked later."""
    return f"CEMP-{event_id:04d}-{student_id:04d}-{secrets.token_hex(3).upper()}"


def _esc(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _signature_block(pdf, centre_x, name, title, signature_file, regular, bold):
    line_y = PAGE_H - 722
    line_w = 184
    pdf.setStrokeColor(GOLD)
    pdf.setLineWidth(2)
    pdf.line(centre_x - line_w / 2, line_y, centre_x + line_w / 2, line_y)

    path = departments.signature_path(signature_file)
    if path:
        img = ImageReader(path)
        iw, ih = img.getSize()
        height = min(58, ih * 120 / iw)
        width = iw * height / ih
        pdf.drawImage(img, centre_x - width / 2, line_y + 4, width=width, height=height, mask="auto")

    pdf.setFillColor(INK)
    y = line_y - 20
    if name:
        pdf.setFont(bold, 15)
        pdf.drawCentredString(centre_x, y, name)
        y -= 17
    pdf.setFont(bold, 11.5)
    pdf.drawCentredString(centre_x, y, title)

def build_certificate_pdf(*, student, event, certificate, college_name, signatory=None):
    """Render the certificate and return it as a BytesIO ready to send.
    (college_name and signatory are kept so existing calls keep working;
    the college name, department and signatories are part of the design picture.)"""
    regular, bold = _fonts()
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(PAGE_W, PAGE_H))
    pdf.setTitle(f"Certificate - {event['title']}")
    pdf.setAuthor("A J Institute of Engineering & Technology")

    # 1. the design
    pdf.drawImage(ImageReader(BACKGROUND), 0, 0, width=PAGE_W, height=PAGE_H)
        # blank out anything printed in the picture for the heading and signature blocks
    pdf.setFillColor(HexColor("#FEFEFE"))
    pdf.setStrokeColor(HexColor("#FEFEFE"))
    pdf.rect(390, PAGE_H - 315, 424, 51, stroke=0, fill=1)      # "DEPARTMENT OF MCA"
    pdf.rect(112, PAGE_H - 773, 240, 122, stroke=0, fill=1)     # left signature block
    pdf.rect(855, PAGE_H - 773, 225, 122, stroke=0, fill=1)     # right signature block
    centre = PAGE_W / 2

    # 2. student name, just above the dotted line under "This is to certify that"
    name = student["name"].strip()
    size = 40
    while size > 22 and pdfmetrics.stringWidth(name, bold, size) > 900:
        size -= 2
    pdf.setFillColor(MAROON)
    pdf.setFont(bold, size)
    pdf.drawCentredString(centre, PAGE_H - 516, name)

        # 2b. organizing department + HOD
    dept_code, dept = departments.resolve(event.get("department"),
                                          event.get("organizer_department"))
    heading = f"DEPARTMENT OF {dept['name'].upper()}"
    h_size = 44
    while h_size > 24 and pdfmetrics.stringWidth(heading, bold, h_size) > 760:
        h_size -= 2
    pdf.setFillColor(INK)
    pdf.setFont(bold, h_size)
    pdf.drawCentredString(centre, PAGE_H - 303, heading)

    _signature_block(pdf, 968, dept.get("hod_name", ""),
                     dept.get("hod_title") or "Head of Department",
                     dept.get("hod_signature"), regular, bold)
    p = departments.PRINCIPAL
    _signature_block(pdf, 229, p["name"], p["title"], p["signature"], regular, bold)

    # 3. the sentence under the dotted line (shrinks a little if the event title is long)
    held_on = event["start_datetime"].strftime("%d %B %Y")
    venue = event.get("venue") or "the campus"
    html = (f"{usn_part}has actively participated in <b>{_esc(event['title'])}</b> "
            f"held on {held_on} at {_esc(venue)}, organized by the Department of "
            f"{_esc(dept['name'])}, {COLLEGE_LINE}.")

    area_w, area_h = 930, 112
    for font_size in (24, 23, 22, 21, 20, 19, 18, 17, 16):
        style = ParagraphStyle("body", fontName=regular, fontSize=font_size,
                               leading=font_size * 1.38, alignment=TA_CENTER, textColor=INK)
        para = Paragraph(html, style)
        _, height = para.wrap(area_w, 1000)
        if height <= area_h:
            break
    para.drawOn(pdf, centre - area_w / 2, PAGE_H - 548 - height)

    # 4. certificate ID and date, in the middle where the third signature would be
    pdf.setFillColor(INK)
    pdf.setFont(regular, 11.5)
    pdf.drawCentredString(centre, PAGE_H - 742, f"Certificate ID: {certificate['certificate_code']}")
    pdf.drawCentredString(centre, PAGE_H - 759, f"Issued on: {certificate['issued_at'].strftime('%d %B %Y')}")

    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer