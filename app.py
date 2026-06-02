"""
Pet Passport Vet - AHC PDF Generation Web Service
v4.3 - France checkboxes: set /AS as well as /V so ticks render in all viewers
"""

import os
import io
from flask import Flask, request, send_file, jsonify
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (NameObject, create_string_object, DecodedStreamObject,
                            DictionaryObject, ArrayObject, NumberObject)
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER

app = Flask(__name__)
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "French.pdf")


# ============================================================
# FONT RESOURCE HELPER
# ============================================================

def get_courier_font_ref(writer):
    """
    Create a standard Courier Type1 font reference.
    Courier is a built-in PDF font — no embedding needed, works in all viewers.
    """
    courier_font = DictionaryObject({
        NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Courier'),
    })
    return writer._add_object(courier_font)


# ============================================================
# APPEARANCE STREAM BUILDER
# ============================================================

def make_ap_stream(writer, text, rect, font_size=8, lines=None, font_ref=None):
    """
    Build a PDF appearance stream for a text field.
    lines: list of strings for multiline rendering.
    font_ref: Courier font indirect reference for Mac Preview compatibility.
    """
    x1, y1, x2, y2 = rect
    w = x2 - x1
    h = y2 - y1

    if lines and len(lines) > 1:
        line_height = font_size + 1
        total_text_h = font_size + line_height
        start_y = min(h - font_size - 1, h * 0.75)
        text_ops = f"2 {start_y:.3f} Td\n"
        for i, line in enumerate(lines):
            if i == 0:
                text_ops += f"({line}) Tj\n"
            else:
                text_ops += f"0 -{line_height:.3f} Td\n({line}) Tj\n"
    else:
        text_ops = f"2 3 Td\n({text}) Tj\n"

    stream_content = (
        f"q\n/Tx BMC \nq\n"
        f"2 1 {w-4:.3f} {h-2:.3f} re\nW\n"
        f"BT\n/Cour {font_size} Tf 0 g\n"
        f"{text_ops}"
        f"ET\nQ\nEMC\nQ\n"
    ).encode('latin-1')

    stream_obj = DecodedStreamObject()
    stream_obj.set_data(stream_content)
    stream_obj[NameObject('/Type')] = NameObject('/XObject')
    stream_obj[NameObject('/Subtype')] = NameObject('/Form')
    stream_obj[NameObject('/BBox')] = ArrayObject([
        NumberObject(0), NumberObject(0),
        NumberObject(round(w, 3)), NumberObject(round(h, 3))
    ])

    if font_ref is not None:
        font_dict = DictionaryObject()
        font_dict[NameObject('/Cour')] = font_ref
        resources = DictionaryObject()
        resources[NameObject('/Font')] = font_dict
        stream_obj[NameObject('/Resources')] = resources

    return writer._add_object(stream_obj)


def set_ap(writer, obj, text, font_size=8, lines=None, font_ref=None):
    """Set /V and /AP on a field annotation object."""
    obj[NameObject('/V')] = create_string_object(text)
    rect = [float(x) for x in obj.get('/Rect', [0, 0, 100, 20])]
    ap_ref = make_ap_stream(writer, text, rect, font_size, lines, font_ref)
    ap_dict = DictionaryObject()
    ap_dict[NameObject('/N')] = ap_ref
    obj[NameObject('/AP')] = ap_dict


def split_to_lines(text, max_chars):
    """Split text into lines of max_chars, breaking at spaces."""
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


# ============================================================
# FIELD BUILDERS
# ============================================================

def build_commodity_description2(d):
    species = d['pet_species']
    sex = d['pet_sex']
    colour = d['pet_colour']
    breed = d['pet_breed']
    chip = d['pet_microchip']
    dob = d['pet_dob']

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
    return f"{line1}\r{line2}".rstrip()


def format_address(raw_address):
    lines = [l.strip() for l in raw_address.replace('\r', '\n').split('\n') if l.strip()]
    if len(lines) <= 3:
        return '\r' + '\r'.join(lines)
    combined = f"{lines[-2]}, {lines[-1]}"
    return '\r' + '\r'.join(lines[:-2] + [combined])


# ============================================================
# FIELD MAPPING
# ============================================================

def get_field_values(d):
    qty = int(d.get("pet_quantity", 1))
    return [
        {"field_id": "Name1",                  "value": d.get("owner_name", "")},
        {"field_id": "Address1",               "value": format_address(d.get("owner_address", ""))},
        {"field_id": "Telephone1",             "value": d.get("owner_telephone", "")},
        {"field_id": "LCA",                    "value": "Animal and Plant Health Agency"},
        {"field_id": "Name2",                  "value": d.get("owner_name", "")},
        {"field_id": "Address2",               "value": "FRANCE"},
        {"field_id": "Telephone2",             "value": d.get("owner_telephone", "")},
        {"field_id": "Commodity description",  "value": d.get("commodity_desc", "")},
        {"field_id": "Quantity",               "value": str(qty)},
        {"field_id": "Text2",  "value": d.get("pet_microchip", "")},
        {"field_id": "Text3",  "value": d.get("rabies_date", "")},
        {"field_id": "Text4",  "value": d.get("rabies_date", "")},
        {"field_id": "Text6",  "value": d.get("batch_number", "")},
        {"field_id": "Text7",  "value": d.get("valid_from", "")},
        {"field_id": "Text8",  "value": d.get("valid_to", "")},
        {"field_id": "Check 2",  "value": "/Yes"},
        {"field_id": "Check 3",  "value": "/Yes"},
        {"field_id": "Check 5",  "value": "/Yes"},
        {"field_id": "Check 6",  "value": "/Yes"},
        {"field_id": "Check 8",  "value": "/Yes"},
        {"field_id": "Check 9",  "value": "/Yes"},
        {"field_id": "Check 10", "value": "/Yes"},
        {"field_id": "Check 13", "value": "/Yes"},
        {"field_id": "Check 14", "value": "/Yes"},
        {"field_id": "OV name",          "value": d.get("ov_name", "")},
        {"field_id": "OV qualification", "value": d.get("ov_qualification", "")},
        {"field_id": "OV address",       "value": d.get("ov_address", "")},
        {"field_id": "OV telephone",     "value": d.get("ov_telephone", "")},
        {"field_id": "Date",             "value": d.get("issue_date", "")},
        {"field_id": "Transponder",  "value": d.get("pet_microchip", "")},
        {"field_id": "AHC number",   "value": d.get("ahc_number", "")},
        {"field_id": "AHC number1",  "value": d.get("ahc_number", "") if qty >= 2 else ""},
        {"field_id": "AHC number2",  "value": d.get("ahc_number", "") if qty >= 3 else ""},
        {"field_id": "AHC number3",  "value": d.get("ahc_number", "") if qty >= 4 else ""},
        {"field_id": "AHC number4",  "value": d.get("ahc_number", "") if qty >= 5 else ""},
        {"field_id": "Placedate",    "value": d.get("place_date", "")},
        {"field_id": "Check 16",     "value": "/Yes"},
        {"field_id": "Check 19",     "value": "/Yes"},
        {"field_id": "Check 20",     "value": "/Yes"},
    ]


# ============================================================
# FRANCE CHECKBOX FIX
# ============================================================

# update_page_form_field_values sets /V but not /AS on checkboxes.
# Without /AS the tick appearance stream is not selected, so the box
# renders blank in strict viewers (Mac Preview, some mobile readers).
# Widget indices on page 9 (0-indexed page 8) confirmed against French.pdf.
FRANCE_CHECKBOX_WIDGETS = {
    1:  "Check 16",
    26: "Check 19",
    31: "Check 20",
}

def apply_france_checkbox_as(writer):
    """Set /AS = /Yes on the three France-specific checkboxes on page 9."""
    page9 = writer.pages[8]
    annots = page9['/Annots']
    for idx in FRANCE_CHECKBOX_WIDGETS:
        obj = annots[idx].get_object()
        obj[NameObject('/AS')] = NameObject('/Yes')


# ============================================================
# FILL THE AHC PDF
# ============================================================

def fill_ahc_bytes(data):
    reader = PdfReader(TEMPLATE_PATH)
    writer = PdfWriter()
    writer.append(reader)

    # Standard field updates
    updates = {fv["field_id"]: fv["value"] for fv in get_field_values(data)}
    for page in writer.pages:
        writer.update_page_form_field_values(page, updates, auto_regenerate=False)

    # Fix checkbox appearance state for France-specific ticks
    apply_france_checkbox_as(writer)

    ref_number = data.get("ahc_number", "")
    vaccine_name = data.get("vaccine_name", "").strip().upper()

    font_ref = get_courier_font_ref(writer)

    for page_num, page in enumerate(writer.pages, 1):
        if '/Annots' not in page:
            continue
        for annot in page['/Annots']:
            obj = annot.get_object()
            name = str(obj.get('/T', ''))

            # Text5: vaccine name (+ manufacturer if provided)
            if name == 'Text5' and vaccine_name:
                mfr = data.get("vaccine_manufacturer", "").strip().upper()
                if mfr:
                    lines = [mfr, vaccine_name]
                else:
                    lines = split_to_lines(vaccine_name, max_chars=9)
                    if len(lines) == 1:
                        lines = [vaccine_name]

                rect = [float(x) for x in obj.get('/Rect', [0, 0, 58, 22])]
                field_w = rect[2] - rect[0]
                field_h = rect[3] - rect[1]
                font_size = 6
                line_height = font_size + 1

                if len(lines) > 1:
                    line1_baseline = 3.5 + line_height
                    start_y = line1_baseline
                else:
                    start_y = (field_h - font_size) / 2 + font_size * 0.212

                text_ops = f"2 {start_y:.3f} Td\n({lines[0]}) Tj\n"
                for line in lines[1:]:
                    text_ops += f"0 -{line_height:.3f} Td\n({line}) Tj\n"

                stream_content = (
                    f"q\n/Tx BMC \nq\n"
                    f"2 1 {field_w-4:.3f} {field_h-2:.3f} re\nW\n"
                    f"BT\n/Cour {font_size} Tf 0 g\n"
                    f"{text_ops}"
                    f"ET\nQ\nEMC\nQ\n"
                ).encode('latin-1')

                stream_obj = DecodedStreamObject()
                stream_obj.set_data(stream_content)
                stream_obj[NameObject('/Type')] = NameObject('/XObject')
                stream_obj[NameObject('/Subtype')] = NameObject('/Form')
                stream_obj[NameObject('/BBox')] = ArrayObject([
                    NumberObject(0), NumberObject(0),
                    NumberObject(round(field_w, 3)), NumberObject(round(field_h, 3))
                ])
                if font_ref is not None:
                    fd = DictionaryObject()
                    fd[NameObject('/Cour')] = font_ref
                    rs = DictionaryObject()
                    rs[NameObject('/Font')] = fd
                    stream_obj[NameObject('/Resources')] = rs

                ap_ref = writer._add_object(stream_obj)
                combined = '\r'.join(lines)
                obj[NameObject('/V')] = create_string_object(combined)
                ap_dict = DictionaryObject()
                ap_dict[NameObject('/N')] = ap_ref
                obj[NameObject('/AP')] = ap_dict

            # Commodity description2 (I.28): nudge text down below column headers
            if name == 'Commodity description2':
                i28_value = build_commodity_description2(data)
                i28_lines = i28_value.split('\r')
                rect = [float(x) for x in obj.get('/Rect', [0, 0, 476, 120])]
                field_w = rect[2] - rect[0]
                field_h = rect[3] - rect[1]
                font_size = 8
                line_height = font_size + 1.5

                top_pad = 2 + 5
                start_y = field_h - font_size - top_pad

                text_ops = f"2 {start_y:.3f} Td\n({i28_lines[0]}) Tj\n"
                for line in i28_lines[1:]:
                    text_ops += f"0 -{line_height:.3f} Td\n({line}) Tj\n"

                stream_content = (
                    f"q\n/Tx BMC \nq\n"
                    f"2 1 {field_w-4:.3f} {field_h-2:.3f} re\nW\n"
                    f"BT\n/Cour {font_size} Tf 0 g\n"
                    f"{text_ops}"
                    f"ET\nQ\nEMC\nQ\n"
                ).encode('latin-1')

                stream_obj = DecodedStreamObject()
                stream_obj.set_data(stream_content)
                stream_obj[NameObject('/Type')] = NameObject('/XObject')
                stream_obj[NameObject('/Subtype')] = NameObject('/Form')
                stream_obj[NameObject('/BBox')] = ArrayObject([
                    NumberObject(0), NumberObject(0),
                    NumberObject(round(field_w, 3)), NumberObject(round(field_h, 3))
                ])
                if font_ref is not None:
                    fd = DictionaryObject()
                    fd[NameObject('/Cour')] = font_ref
                    rs = DictionaryObject()
                    rs[NameObject('/Font')] = fd
                    stream_obj[NameObject('/Resources')] = rs

                ap_ref = writer._add_object(stream_obj)
                obj[NameObject('/V')] = create_string_object(i28_value)
                ap_dict = DictionaryObject()
                ap_dict[NameObject('/N')] = ap_ref
                obj[NameObject('/AP')] = ap_dict

    stamp_reference_numbers(writer, ref_number)

    output = io.BytesIO()
    writer.write(output)
    output.seek(0)
    return output


# ============================================================
# REFERENCE NUMBER STAMP
# ============================================================

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


def stamp_reference_numbers(writer, ref_number):
    """
    Stamp the certificate reference number onto each page (1-8) as permanent
    page content using a reportlab overlay merged via merge_page().
    """
    if not ref_number:
        return
    for page_num, rect in REF_NUMBER_RECTS.items():
        if page_num > len(writer.pages):
            continue
        page = writer.pages[page_num - 1]
        pw = float(page.mediabox.width)
        ph = float(page.mediabox.height)

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(pw, ph))
        c.setFont("Courier", 9)
        c.setFillColorRGB(0, 0, 0)
        c.drawString(rect[0] + 2, rect[1] + 3, ref_number)
        c.save()
        buf.seek(0)

        overlay_page = PdfReader(buf).pages[0]
        page.merge_page(overlay_page)


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
    return jsonify({"status": "ok", "service": "Pet Passport Vet AHC Generator", "version": "4.3"})


@app.route("/debug", methods=["GET"])
def debug():
    test = {"pet_species": "CANIS LUPUS FAMILIARIS", "pet_sex": "MALE",
            "pet_colour": "BLACK", "pet_breed": "LABRADOR",
            "pet_microchip": "958000080144977", "pet_dob": "17/03/2023"}
    return jsonify({"i28_field": build_commodity_description2(test), "version": "4.3"})


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
