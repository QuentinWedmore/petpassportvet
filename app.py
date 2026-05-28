"""
Pet Passport Vet - AHC PDF Generation Web Service
Receives customer/vet data as JSON, returns a filled AHC PDF
with certified copy appended.
Deploy to Render.com as a Python web service.
"""

import os
import io
from flask import Flask, request, send_file, jsonify
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER

app = Flask(__name__)

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "French.pdf")


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

    species_parts = species.split()
    s1 = ' '.join(species_parts[:2]) if len(species_parts) >= 3 else species
    s2 = ' '.join(species_parts[2:]) if len(species_parts) >= 3 else ''

    colour_parts = colour.split()
    c1 = ' '.join(colour_parts[:2]) if len(colour_parts) >= 3 else colour
    c2 = ' '.join(colour_parts[2:]) if len(colour_parts) >= 3 else ''

    breed_parts = breed.split()
    b1 = breed_parts[0] if len(breed_parts) >= 2 else breed
    b2 = ' '.join(breed_parts[1:]) if len(breed_parts) >= 2 else ''

    line1 = f"{s1:<13}{sex:<7}{c1:<11}{b1:<10}{chip:<20}{'TRANSPONDER':<19}{dob}"
    line2 = f"{s2:<13}       {c2:<11}{b2}"

    return f"{line1}\r{line2}".rstrip()


def format_address(raw_address):
    lines = [l.strip() for l in raw_address.replace('\r', '\n').split('\n') if l.strip()]
    if len(lines) <= 3:
        return '\r'.join(lines)
    if len(lines) >= 4:
        postcode = lines[-1]
        county = lines[-2]
        combined = f"{county}, {postcode}"
        result = lines[:-2] + [combined]
        return '\r'.join(result[:4])
    return '\r'.join(lines[:4])


# ============================================================
# AHC FIELD MAPPING
# ============================================================

def get_field_values(d):
    raw_address = d.get("owner_address", "")
    formatted_address = format_address(raw_address)

    return [
        {"field_id": "Name1",                   "value": d.get("owner_name", "")},
        {"field_id": "Address1",                "value": formatted_address},
        {"field_id": "Telephone1",              "value": d.get("owner_telephone", "")},
        {"field_id": "LCA",                     "value": "Animal and Plant Health Agency"},
        {"field_id": "Name2",                   "value": d.get("owner_name", "")},
        {"field_id": "Address2",                "value": "FRANCE"},
        {"field_id": "Telephone2",              "value": d.get("owner_telephone", "")},
        {"field_id": "Commodity description",   "value": d.get("commodity_desc", "")},
        {"field_id": "Commodity description2",  "value": build_commodity_description2(d)},
        {"field_id": "Quantity",                "value": d.get("pet_quantity", "1")},
        {"field_id": "Text1",                   "value": d.get("ahc_number", "")},
        {"field_id": "Text2",   "value": d.get("pet_microchip", "")},
        {"field_id": "Text3",   "value": d.get("rabies_date", "")},
        {"field_id": "Text4",   "value": d.get("rabies_date", "")},
        {"field_id": "Text5",   "value": d.get("vaccine_manufacturer", "").strip().upper()},
        {"field_id": "Text6",   "value": d.get("batch_number", "")},
        {"field_id": "Text7",   "value": d.get("valid_from", "")},
        {"field_id": "Text8",   "value": d.get("valid_to", "")},
        {"field_id": "Text13",  "value": d.get("vaccine_name", "").strip().upper()},
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
        {"field_id": "Transponder", "value": d.get("pet_microchip", "")},
        {"field_id": "AHC number",  "value": d.get("ahc_number", "")},
        {"field_id": "Placedate",   "value": d.get("place_date", "")},
        {"field_id": "Check 16",    "value": "/Yes"},
        {"field_id": "Check 19",    "value": "/Yes"},
        {"field_id": "Check 20",    "value": "/Yes"},
    ]


# ============================================================
# FILL THE AHC PDF
# ============================================================

def fill_ahc_bytes(data):
    reader = PdfReader(TEMPLATE_PATH)
    writer = PdfWriter()
    writer.append(reader)

    updates = {fv["field_id"]: fv["value"] for fv in get_field_values(data)}

    for page in writer.pages:
        writer.update_page_form_field_values(page, updates, auto_regenerate=False)

    output = io.BytesIO()
    writer.write(output)
    output.seek(0)
    return output


# ============================================================
# GENERATE CERTIFIED COPY PAGE
# ============================================================

def generate_certified_copy(data):
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20*mm,
        rightMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'Title', parent=styles['Normal'],
        fontSize=13, fontName='Helvetica-Bold',
        alignment=TA_CENTER, spaceAfter=4
    )
    section_style = ParagraphStyle(
        'Section', parent=styles['Normal'],
        fontSize=11, fontName='Helvetica-Bold',
        spaceBefore=10, spaceAfter=4,
        textColor=colors.HexColor('#1a1a2e')
    )
    field_style = ParagraphStyle(
        'Field', parent=styles['Normal'],
        fontSize=10, fontName='Helvetica',
        spaceAfter=3, leftIndent=10
    )
    confirm_style = ParagraphStyle(
        'Confirm', parent=styles['Normal'],
        fontSize=10, fontName='Helvetica',
        spaceAfter=8, alignment=TA_LEFT
    )

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
            confirm_style
        ),

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
# MERGE AHC + CERTIFIED COPY
# ============================================================

def merge_pdfs(ahc_bytes, certified_copy_bytes):
    writer = PdfWriter()

    ahc_reader = PdfReader(ahc_bytes)
    for page in ahc_reader.pages:
        writer.add_page(page)

    copy_reader = PdfReader(certified_copy_bytes)
    for page in copy_reader.pages:
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
    return jsonify({"status": "ok", "service": "Pet Passport Vet AHC Generator", "version": "3.0"})


@app.route("/debug", methods=["GET"])
def debug():
    test_data = {
        "pet_species": "CANIS LUPUS FAMILIARIS",
        "pet_sex": "MALE",
        "pet_colour": "BLACK",
        "pet_breed": "LABRADOR",
        "pet_microchip": "958000080144977",
        "pet_dob": "17/03/2023",
    }
    result = build_commodity_description2(test_data)
    return jsonify({"i28_field": result, "repr": repr(result)})


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

        # Generate filled AHC PDF
        ahc_bytes = fill_ahc_bytes(data)

        # Generate certified copy page
        certified_copy_bytes = generate_certified_copy(data)

        # Merge into one document
        merged = merge_pdfs(ahc_bytes, certified_copy_bytes)

        owner = data.get("owner_name", "unknown").replace(" ", "_")
        pet = data.get("pet_name", "pet").replace(" ", "_")
        filename = f"AHC_{owner}_{pet}.pdf"

        return send_file(
            merged,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
