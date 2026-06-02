"""
Pet Passport Vet - AHC PDF Generation Web Service
v6.0 - Overlay architecture (viewer-proof).

Design
------
The France AHC strikethroughs were stored in the form template as fragile
"orphan" widget annotations. Strict viewers (Acrobat, Mac Preview) regenerate
form appearances on save and drop those widgets, so any approach that round-
tripped the form through pypdf's field handling broke the strikes.

v6.0 removes form handling from the request path entirely:

  1. ONE-TIME prep (build_base_template.py, run offline): flatten Quentin's
     correct template into `base_france.pdf` — strikes and practice details
     burned into static page content (honoring each widget's Hidden /F flag so
     cleared strikes stay clear), checkboxes removed, all widgets and the
     AcroForm stripped. The result renders identically in every viewer.

  2. PER-CERTIFICATE (this app): load the flat base and draw the variable
     pet/owner data ON TOP as a content overlay at fixed coordinates. No form
     fields are ever touched, so nothing can regenerate or drop the strikes.

If Quentin ever changes his standard strike pattern, re-run the offline
flattener to rebuild base_france.pdf; this app does not need to change.
"""

import os
import io
from flask import Flask, request, send_file, jsonify
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER

app = Flask(__name__)

# The flattened static base (produced once by the offline flattener).
BASE_PATH = os.path.join(os.path.dirname(__file__), "base_france.pdf")


# ============================================================
# FIELD COORDINATES
# Extracted from the original form template. Each entry is the PDF rect
# [x0, y0, x1, y1] (points, origin bottom-left) where that field's text sits.
# Text is drawn relative to these rects in the overlay.
# ============================================================

FIELD_RECTS = {
    # page 1 — consignor / consignee / commodity
    "Name1":                 (1, [124.4, 657.1, 295.4, 671.4]),
    "Address1":              (1, [141.3, 621.7, 294.8, 662.0]),
    "Telephone1":            (1, [114.0, 611.3, 294.8, 624.2]),
    "Name2":                 (1, [125.0, 568.3, 296.0, 580.4]),
    "Address2":              (1, [140.7, 538.5, 296.0, 565.6]),
    "Telephone2":            (1, [113.2, 512.0, 295.1, 526.0]),
    "Commodity description": (1, [61.6, 355.7, 363.8, 388.6]),
    "Commodity description2":(1, [60.4, 80.3, 536.3, 199.8]),   # I.28 identification block
    "Quantity":              (1, [510.8, 351.3, 535.6, 367.9]),
    # page 4 — vaccination table row
    "Text2":  (4, [57.2, 450.4, 163.1, 465.2]),   # transponder/tattoo
    "Text3":  (4, [160.7, 450.4, 232.9, 465.1]),  # date of vaccination
    "Text4":  (4, [232.6, 449.5, 289.0, 464.9]),  # date of vaccination (2)
    "Text5":  (4, [287.6, 447.1, 346.1, 468.7]),  # vaccine name + manufacturer
    "Text6":  (4, [344.1, 449.8, 396.2, 465.8]),  # batch number
    "Text7":  (4, [394.5, 450.1, 441.3, 465.5]),  # valid from
    "Text8":  (4, [436.6, 449.3, 487.8, 465.7]),  # valid to
    # page 8 — date
    "Date":   (8, [140.3, 536.1, 211.5, 553.6]),
    # page 9 — declaration table
    "Transponder": (9, [75.0, 490.6, 307.5, 510.3]),
    "AHC number":  (9, [306.8, 491.2, 523.7, 510.3]),
    "AHC number1": (9, [307.0, 473.0, 523.8, 492.1]),
    "AHC number2": (9, [306.9, 453.9, 523.7, 473.0]),
    "AHC number3": (9, [307.1, 435.7, 523.9, 454.8]),
    "AHC number4": (9, [307.0, 417.8, 523.8, 436.9]),
}

# Certificate reference number boxes (II.a / I.2) per page, stamped on pages 1-8.
REF_NUMBER_RECTS = {
    1: [303.1, 658.0, 428.4, 672.2],
    2: [275.2, 626.9, 400.5, 642.3],
    3: [265.1, 647.8, 390.4, 663.2],
    4: [232.5, 659.5, 357.8, 674.9],
    5: [229.0, 652.9, 354.3, 668.3],
    6: [225.8, 649.4, 351.1, 664.8],
    7: [226.1, 648.1, 351.4, 663.5],
    8: [218.7, 647.1, 344.0, 662.5],
}


# ============================================================
# TEXT BUILDERS
# ============================================================

def split_to_lines(text, max_chars):
    if len(text) <= max_chars:
        return [text]
    words = text.split()
    lines, current = [], ""
    for word in words:
        if current and len(current) + 1 + len(word) > max_chars:
            lines.append(current)
            current = word
        else:
            current = (current + " " + word).strip()
    if current:
        lines.append(current)
    return lines


def build_i28_lines(d):
    """Two-line I.28 identification row (species/sex/colour/breed/chip/system/dob)."""
    species = d['pet_species']; sex = d['pet_sex']; colour = d['pet_colour']
    breed = d['pet_breed']; chip = d['pet_microchip']; dob = d['pet_dob']

    sp = species.split()
    s1 = ' '.join(sp[:2]) if len(sp) >= 3 else species
    s2 = ' '.join(sp[2:]) if len(sp) >= 3 else ''
    cp = colour.split()
    c1 = ' '.join(cp[:2]) if len(cp) >= 3 else colour
    c2 = ' '.join(cp[2:]) if len(cp) >= 3 else ''
    bp = breed.split()
    b1 = bp[0] if len(bp) >= 2 else breed
    b2 = ' '.join(bp[1:]) if len(bp) >= 2 else ''

    line1 = f"{s1:<13}{sex:<7}{c1:<11}{b1:<10}{chip:<20}{'TRANSPONDER':<19}{dob}"
    line2 = f"{s2:<13}       {c2:<11}{b2}"
    return [line1, line2.rstrip()] if line2.strip() else [line1]


def address_lines(raw_address):
    lines = [l.strip() for l in raw_address.replace('\r', '\n').split('\n') if l.strip()]
    if len(lines) <= 3:
        return lines
    combined = f"{lines[-2]}, {lines[-1]}"
    return lines[:-2] + [combined]


# ============================================================
# OVERLAY DRAWING
# ============================================================

def _draw_overlay_for_page(c, page_num, data):
    """Draw all field text that belongs on `page_num` onto canvas `c`."""
    qty = int(data.get("pet_quantity", 1))

    def field_on(name):
        p, rect = FIELD_RECTS[name]
        return p == page_num, rect

    def text(name, value, font="Courier", size=9, dy=3, dx=2):
        if not value:
            return
        on, rect = field_on(name)
        if not on:
            return
        c.setFont(font, size)
        c.setFillColorRGB(0, 0, 0)
        c.drawString(rect[0] + dx, rect[1] + dy, str(value))

    def text_lines(name, lines, font="Courier", size=8, line_gap=1.5,
                   top_pad=2, dx=2):
        on, rect = field_on(name)
        if not on or not lines:
            return
        fh = rect[3] - rect[1]
        lh = size + line_gap
        start_y = rect[3] - size - top_pad   # top-aligned
        c.setFont(font, size)
        c.setFillColorRGB(0, 0, 0)
        y = start_y
        for ln in lines:
            c.drawString(rect[0] + dx, y, ln)
            y -= lh

    # --- page 1 ---
    if page_num == 1:
        text("Name1", data.get("owner_name", ""))
        text_lines("Address1", address_lines(data.get("owner_address", "")),
                   size=8, line_gap=0.5)
        text("Telephone1", data.get("owner_telephone", ""))
        text("Name2", data.get("owner_name", ""))
        text("Address2", "FRANCE")
        text("Telephone2", data.get("owner_telephone", ""))
        text("Commodity description", data.get("commodity_desc", ""))
        text("Quantity", str(qty))
        # I.28 — two lines, nudged down below the column headers
        on, rect = field_on("Commodity description2")
        if on:
            lines = build_i28_lines(data)
            fh = rect[3] - rect[1]
            size = 8; lh = size + 1.5
            start_y = rect[3] - size - (2 + 5)   # extra 5pt nudge
            c.setFont("Courier", size); c.setFillColorRGB(0, 0, 0)
            y = start_y
            for ln in lines:
                c.drawString(rect[0] + 2, y, ln)
                y -= lh

    # --- page 4: vaccination row ---
    elif page_num == 4:
        text("Text2", data.get("pet_microchip", ""), size=8)
        text("Text3", data.get("rabies_date", ""), size=8)
        text("Text4", data.get("rabies_date", ""), size=8)
        text("Text6", data.get("batch_number", ""), size=8)
        # Validity dates: size 7 so "dd/mm/yyyy" (42pt) fits the ~47pt columns
        # without spilling into the adjacent column.
        text("Text7", data.get("valid_from", ""), size=7, dx=1)
        text("Text8", data.get("valid_to", ""), size=7, dx=1)
        # Text5: vaccine manufacturer + name, wrapped to fit the narrow cell.
        on, rect = field_on("Text5")
        vaccine_name = data.get("vaccine_name", "").strip().upper()
        if on and vaccine_name:
            mfr = data.get("vaccine_manufacturer", "").strip().upper()
            cell_w = rect[2] - rect[0]
            size = 5
            # max chars per line for Courier: width per char = 0.6 * size
            char_w = 0.6 * size
            max_chars = max(6, int((cell_w - 4) / char_w))
            lines = []
            if mfr:
                lines += split_to_lines(mfr, max_chars)
            lines += split_to_lines(vaccine_name, max_chars)
            lh = size + 0.3
            n = len(lines)
            # Centre the baseline span, with a small downward nudge so the top
            # line clears the cell's top border comfortably.
            mid = (rect[1] + rect[3]) / 2
            span = (n - 1) * lh
            top_baseline = mid + span / 2 - size * 0.35 - 0.6
            c.setFont("Courier", size); c.setFillColorRGB(0, 0, 0)
            y = top_baseline
            for ln in lines:
                c.drawString(rect[0] + 2, y, ln)
                y -= lh

    # --- page 8: date ---
    elif page_num == 8:
        text("Date", data.get("issue_date", ""))

    # --- page 9: declaration table ---
    elif page_num == 9:
        text("Transponder", data.get("pet_microchip", ""))
        text("AHC number", data.get("ahc_number", ""))
        if qty >= 2: text("AHC number1", data.get("ahc_number", ""))
        if qty >= 3: text("AHC number2", data.get("ahc_number", ""))
        if qty >= 4: text("AHC number3", data.get("ahc_number", ""))
        if qty >= 5: text("AHC number4", data.get("ahc_number", ""))


def _draw_reference_number(c, page_num, ref_number):
    if not ref_number or page_num not in REF_NUMBER_RECTS:
        return
    rect = REF_NUMBER_RECTS[page_num]
    c.setFont("Courier", 9)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(rect[0] + 2, rect[1] + 3, ref_number)


def fill_ahc_bytes(data):
    """Load the flat base and overlay all pet/owner data as page content."""
    reader = PdfReader(BASE_PATH)
    writer = PdfWriter()
    ref_number = data.get("ahc_number", "")

    for idx, page in enumerate(reader.pages):
        page_num = idx + 1
        pw = float(page.mediabox.width)
        ph = float(page.mediabox.height)

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(pw, ph))
        _draw_overlay_for_page(c, page_num, data)
        _draw_reference_number(c, page_num, ref_number)
        c.save()
        buf.seek(0)

        overlay = PdfReader(buf).pages[0]
        page.merge_page(overlay)
        writer.add_page(page)

    output = io.BytesIO()
    writer.write(output)
    output.seek(0)
    return output


# ============================================================
# CERTIFIED COPY PAGE
# ============================================================

def generate_certified_copy(data):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('Title', parent=styles['Normal'],
        fontSize=13, fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=4)
    section_style = ParagraphStyle('Section', parent=styles['Normal'],
        fontSize=11, fontName='Helvetica-Bold', spaceBefore=10, spaceAfter=4,
        textColor=colors.HexColor('#1a1a2e'))
    field_style = ParagraphStyle('Field', parent=styles['Normal'],
        fontSize=10, fontName='Helvetica', spaceAfter=3, leftIndent=10)
    confirm_style = ParagraphStyle('Confirm', parent=styles['Normal'],
        fontSize=10, fontName='Helvetica', spaceAfter=8)

    def field(label, value):
        return Paragraph(f'<b>{label}:</b> {value}', field_style)

    address = data.get('owner_address', '').replace('\r', ', ')
    vaccine_brand = f"{data.get('vaccine_manufacturer', '')} {data.get('vaccine_name', '')}".strip()

    elements = [
        Paragraph('Pet Passport Vet', title_style),
        Paragraph('Microchip scanning and rabies vaccination certificate', title_style),
        Spacer(1, 4*mm),
        HRFlowable(width='100%', thickness=2, color=colors.HexColor('#2d4a8a')),
        Spacer(1, 4*mm),
        Paragraph('Owner details', section_style),
        field('Full Name', data.get('owner_name', '')),
        field('Address', address),
        field('Telephone number', data.get('owner_telephone', '')),
        Spacer(1, 3*mm),
        HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#cccccc')),
        Paragraph("Pet's details", section_style),
        field('Name', data.get('pet_name', '')),
        field('Species', data.get('pet_species', '')),
        field('Breed', data.get('pet_breed', '')),
        field('Sex', data.get('pet_sex', '')),
        field('Colour', data.get('pet_colour', '')),
        field('Date of Birth', data.get('pet_dob', '')),
        field('Microchip number', data.get('pet_microchip', '')),
        field('Date of reading microchip', data.get('issue_date', '')),
        Spacer(1, 3*mm),
        HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#cccccc')),
        Paragraph('Rabies vaccination details', section_style),
        field('Date of vaccination', data.get('rabies_date', '')),
        field('Vaccination valid from', data.get('valid_from', '')),
        field('Vaccination valid to', data.get('valid_to', '')),
        field('Vaccine manufacturer and brand', vaccine_brand),
        field('Batch number', data.get('batch_number', '')),
        Spacer(1, 4*mm),
        HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#cccccc')),
        Spacer(1, 4*mm),
        Paragraph(
            'This certificate is to confirm that the animal named above has been given a rabies vaccine '
            'and that the microchip was scanned and confirmed prior to administration of the vaccine.',
            confirm_style),
        Spacer(1, 4*mm),
        HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#cccccc')),
        Paragraph('Details of the vet who completed this certificate:', section_style),
        field('Name', data.get('ov_name', '')),
        field('SP Number', data.get('ov_sp_number', '637867')),
        field('Date', data.get('issue_date', '')),
        Spacer(1, 12*mm),
        Paragraph('Signature: ___________________________________', field_style),
    ]
    doc.build(elements)
    buffer.seek(0)
    return buffer


# ============================================================
# MERGE
# ============================================================

def merge_pdfs(ahc_bytes, certified_copy_bytes):
    writer = PdfWriter()
    for page in PdfReader(ahc_bytes).pages:
        writer.add_page(page)
    for page in PdfReader(certified_copy_bytes).pages:
        writer.add_page(page)
    output = io.BytesIO()
    writer.write(output)
    output.seek(0)
    return output


# ============================================================
# ROUTES
# ============================================================

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Pet Passport Vet AHC Generator", "version": "6.0"})


@app.route("/debug", methods=["GET"])
def debug():
    test = {"pet_species": "CANIS LUPUS FAMILIARIS", "pet_sex": "MALE",
            "pet_colour": "BLACK", "pet_breed": "LABRADOR",
            "pet_microchip": "958000080144977", "pet_dob": "17/03/2023"}
    return jsonify({"i28_lines": build_i28_lines(test), "version": "6.0"})


@app.route("/generate", methods=["POST"])
def generate():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data received"}), 400
        required = ["owner_name", "pet_microchip", "pet_species"]
        missing = [f for f in required if not data.get(f)]
        if missing:
            return jsonify({"error": f"Missing required fields: {missing}"}), 400

        ahc_bytes = fill_ahc_bytes(data)
        cert_bytes = generate_certified_copy(data)
        merged = merge_pdfs(ahc_bytes, cert_bytes)

        owner = data.get("owner_name", "unknown").replace(" ", "_")
        pet = data.get("pet_name", "pet").replace(" ", "_")
        return send_file(merged, mimetype="application/pdf",
                        as_attachment=True, download_name=f"AHC_{owner}_{pet}.pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
