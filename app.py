"""
Pet Passport Vet - AHC PDF Generation Web Service
v3.7 - Courier Type1 font, reliable reference numbers
"""

import os
import io
from flask import Flask, request, send_file, jsonify
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (NameObject, create_string_object, DecodedStreamObject,
                            DictionaryObject, ArrayObject, NumberObject)
from reportlab.lib.pagesizes import A4
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
        # For multiline: fit both lines within the field height
        # line1 near top, line2 just below with minimal spacing
        line_height = font_size + 1  # tight spacing to keep within field
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

    # Font resources — required for Mac Preview and other strict PDF viewers
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
        return '\r'.join(lines)
    combined = f"{lines[-2]}, {lines[-1]}"
    return '\r'.join(lines[:-2] + [combined])[:4 * 40]


# ============================================================
# FIELD MAPPING
# Note: Text1 and Text13 are excluded here — handled via AP streams below
# to avoid double-rendering
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
        {"field_id": "Commodity description2", "value": build_commodity_description2(d)},
        {"field_id": "Quantity",               "value": str(qty)},
        # Text1 excluded — set via AP stream
        {"field_id": "Text2",  "value": d.get("pet_microchip", "")},
        {"field_id": "Text3",  "value": d.get("rabies_date", "")},
        {"field_id": "Text4",  "value": d.get("rabies_date", "")},
        # Text5 excluded — set via AP stream (vaccine name + manufacturer)
        {"field_id": "Text6",  "value": d.get("batch_number", "")},
        {"field_id": "Text7",  "value": d.get("valid_from", "")},
        {"field_id": "Text8",  "value": d.get("valid_to", "")},
        # Text13 excluded — set via AP stream
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
# FILL THE AHC PDF
# ============================================================

def fill_ahc_bytes(data):
    reader = PdfReader(TEMPLATE_PATH)
    writer = PdfWriter()
    writer.append(reader)

    # Standard field updates (excludes Text1 and Text13)
    updates = {fv["field_id"]: fv["value"] for fv in get_field_values(data)}
    for page in writer.pages:
        writer.update_page_form_field_values(page, updates, auto_regenerate=False)

    ref_number = data.get("ahc_number", "")
    vaccine_name = data.get("vaccine_name", "").strip().upper()

    # Get Courier font reference for Mac Preview compatibility
    font_ref = get_courier_font_ref(writer)

    # Set AP streams for Text1 (cert reference, pages 1-8) and Text13 (vaccine name)
    vaccine_lines = split_to_lines(vaccine_name, max_chars=9) if vaccine_name else None

    for page_num, page in enumerate(writer.pages, 1):
        if '/Annots' not in page:
            continue
        for annot in page['/Annots']:
            obj = annot.get_object()
            name = str(obj.get('/T', ''))
            parent = obj.get('/Parent')

            # Named Text1 field (page 1)
            if name == 'Text1':
                set_ap(writer, obj, ref_number, font_size=8, font_ref=font_ref)

            # Unnamed children of Text1 (II.a header, pages 1-8)
            if not name and parent:
                parent_obj = parent.get_object()
                if str(parent_obj.get('/T', '')) == 'Text1':
                    set_ap(writer, obj, ref_number, font_size=8, font_ref=font_ref)

            # Text5: vaccine name (+ manufacturer if provided) — this field sits fully
            # within the visible table row, unlike Text13 which is mostly below it.
            # Use two lines if name is long, centred vertically in the field.
            if name == 'Text5' and vaccine_name:
                mfr = data.get("vaccine_manufacturer", "").strip().upper()
                # Build lines: manufacturer on line 1 if present, name on line 1 (or 2)
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
                line_height = font_size + 2  # 8pt between baselines

                if len(lines) > 1:
                    # Centre two lines vertically
                    total_h = font_size + line_height
                    start_y = (field_h + total_h) / 2 - font_size * 0.718
                else:
                    # Centre single line
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

            # Text13: leave empty (Text5 handles vaccine name for row 1)

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
    return jsonify({"status": "ok", "service": "Pet Passport Vet AHC Generator", "version": "3.7"})


@app.route("/debug", methods=["GET"])
def debug():
    test = {"pet_species": "CANIS LUPUS FAMILIARIS", "pet_sex": "MALE",
            "pet_colour": "BLACK", "pet_breed": "LABRADOR",
            "pet_microchip": "958000080144977", "pet_dob": "17/03/2023"}
    return jsonify({"i28_field": build_commodity_description2(test), "version": "3.7"})


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
