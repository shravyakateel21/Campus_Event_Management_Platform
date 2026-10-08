"""Certificate code generation and PDF rendering."""

import secrets
from io import BytesIO

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

INK = HexColor("#16202A")
ACCENT = HexColor("#1F5FBF")
MUTED = HexColor("#5A6773")


def new_certificate_code(event_id, student_id):
    """A short code printed on the PDF so a certificate can be checked later."""
    return f"CEMP-{event_id:04d}-{student_id:04d}-{secrets.token_hex(3).upper()}"


def build_certificate_pdf(*, student, event, certificate, college_name, signatory):
    """Render the certificate and return it as a BytesIO ready to send."""
    buffer = BytesIO()
    width, height = landscape(A4)
    pdf = canvas.Canvas(buffer, pagesize=landscape(A4))
    pdf.setTitle(f"Certificate - {event['title']}")

    # Border
    pdf.setStrokeColor(ACCENT)
    pdf.setLineWidth(3)
    pdf.rect(14 * mm, 14 * mm, width - 28 * mm, height - 28 * mm)
    pdf.setStrokeColor(INK)
    pdf.setLineWidth(0.7)
    pdf.rect(18 * mm, 18 * mm, width - 36 * mm, height - 36 * mm)

    centre = width / 2

    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawCentredString(centre, height - 48 * mm, college_name)

    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 12)
    pdf.drawCentredString(centre, height - 58 * mm, "Certificate of Participation")

    pdf.setFillColor(INK)
    pdf.setFont("Helvetica", 13)
    pdf.drawCentredString(centre, height - 80 * mm, "This is to certify that")

    pdf.setFont("Helvetica-Bold", 30)
    pdf.drawCentredString(centre, height - 96 * mm, student["name"])

    if student.get("usn"):
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 11)
        pdf.drawCentredString(centre, height - 104 * mm, f"USN {student['usn']}")

    pdf.setFillColor(INK)
    pdf.setFont("Helvetica", 13)
    pdf.drawCentredString(centre, height - 120 * mm, "has attended")

    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawCentredString(centre, height - 132 * mm, event["title"])

    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 11)
    held_on = event["start_datetime"].strftime("%d %B %Y")
    venue = event.get("venue") or "the campus"
    pdf.drawCentredString(centre, height - 142 * mm, f"held on {held_on} at {venue}")

    # Footer: code on the left, signature on the right
    pdf.setFont("Helvetica", 9)
    pdf.drawString(30 * mm, 32 * mm, f"Certificate ID  {certificate['certificate_code']}")
    pdf.drawString(30 * mm, 26 * mm, f"Issued  {certificate['issued_at'].strftime('%d %b %Y')}")

    pdf.setStrokeColor(INK)
    pdf.setLineWidth(0.7)
    pdf.line(width - 90 * mm, 36 * mm, width - 30 * mm, 36 * mm)
    pdf.setFillColor(INK)
    pdf.setFont("Helvetica", 10)
    pdf.drawCentredString(width - 60 * mm, 29 * mm, signatory)

    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer