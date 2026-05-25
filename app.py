"""
Pet Passport Vet - AHC PDF Generation Web Service
Receives customer/vet data as JSON, returns a filled AHC PDF.
Deploy to Render.com as a Python web service.
"""

import os
import io
from flask import Flask, request, send_file, jsonify
from pypdf import PdfReader, PdfWriter

app = Flask(__name__)

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "French.pdf")

# ============================================================
# FIELD BUILDERS
# ============================================================

def build_commodity_description2(d):
    """
    Build the I.28 identification table using precise column positions
    measured from official completed AHC examples.

    Column start positions (chars):
    Species: 0, Sex: 13, Colour: 20, Breed: 31, Microchip: 41,
    ID system: 61, DOB: 80
    """
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
    """
    Format address into max 4 lines fitting the Address1 field (153pt wide, 40pt tall).
    Combines town and county, puts postcode on same line as county.
    Input lines are split by newline characters.
    """
    lines = [l.strip() for l in raw_address.replace('\r', '\n').split('\n') if l.strip()]

    if len(lines) <= 3:
        return '\r'.join(lines)

    # 4+ lines: combine the last two non-postcode lines if needed
    # Typical UK address: line1, line2, town, county, postcode
    # Strategy: keep street lines, combine county + postcode on last line
    if len(lines) >= 4:
        # Put postcode on same line as the line before it
        postcode = lines[-1]
        county = lines[-2]
        combined = f"{county}, {postcode}"
        result = lines[:-2] + [combined]
        return '\r'.join(result[:4])

    return '\r'.join(lines[:4])


# ============================================================
# FIELD MAPPING
# ============================================================

def get_field_values(d):
    raw_address = d.get("owner_address", "")
    formatted_address = format_address(raw_address)

    return [
        # Part I - Consignor (owner)
        {"field_id": "Name1",                   "value": d.get("owner_name", "")},
        {"field_id": "Address1",                "value": formatted_address},
        {"field_id": "Telephone1",              "value": d.get("owner_telephone", "")},
        {"field_id": "LCA",                     "value": "Animal and Plant Health Agency"},

        # Part I - Consignee
        {"field_id": "Name2",                   "value": d.get("owner_name", "")},
        {"field_id": "Address2",                "value": "FRANCE"},
        {"field_id": "Telephone2",              "value": d.get("owner_telephone", "")},

        # Part I - Commodity
        {"field_id": "Commodity description",   "value": d.get("commodity_desc", "")},
        {"field_id": "Commodity description2",  "value": build_commodity_description2(d)},
        {"field_id": "Quantity",                "value": d.get("pet_quantity", "1")},
        {"field_id": "Text1",                   "value": d.get("ahc_number", "")},

        # Part II - Vaccination table (Page 4)
        # Text5 = Manufacturer name, Text13 = Vaccine name (confirmed from completed example)
        {"field_id": "Text2",   "value": d.get("pet_microchip", "")},
        {"field_id": "Text3",   "value": d.get("rabies_date", "")},
        {"field_id": "Text4",   "value": d.get("rabies_date", "")},
        {"field_id": "Text5",   "value": d.get("vaccine_manufacturer", "").strip().upper()},
        {"field_id": "Text6",   "value": d.get("batch_number", "")},
        {"field_id": "Text7",   "value": d.get("valid_from", "")},
        {"field_id": "Text8",   "value": d.get("valid_to", "")},
        {"field_id": "Text13",  "value": d.get("vaccine_name", "").strip().upper()},

        # Part II - Standard checkboxes for France
        {"field_id": "Check 2",  "value": "/Yes"},
        {"field_id": "Check 3",  "value": "/Yes"},
        {"field_id": "Check 5",  "value": "/Yes"},
        {"field_id": "Check 6",  "value": "/Yes"},
        {"field_id": "Check 8",  "value": "/Yes"},
        {"field_id": "Check 9",  "value": "/Yes"},
        {"field_id": "Check 10", "value": "/Yes"},
        {"field_id": "Check 13", "value": "/Yes"},
        {"field_id": "Check 14", "value": "/Yes"},

        # OV details (Page 8)
        {"field_id": "OV name",          "value": d.get("ov_name", "")},
        {"field_id": "OV qualification", "value": d.get("ov_qualification", "")},
        {"field_id": "OV address",       "value": d.get("ov_address", "")},
        {"field_id": "OV telephone",     "value": d.get("ov_telephone", "")},
        {"field_id": "Date",             "value": d.get("issue_date", "")},

        # Declaration page (Page 9)
        {"field_id": "Transponder", "value": d.get("pet_microchip", "")},
        {"field_id": "AHC number",  "value": d.get("ahc_number", "")},
        {"field_id": "Placedate",   "value": d.get("place_date", "")},
        {"field_id": "Check 16",    "value": "/Yes"},
        {"field_id": "Check 19",    "value": "/Yes"},
        {"field_id": "Check 20",    "value": "/Yes"},
    ]


# ============================================================
# FILL THE PDF - returns bytes
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
# ROUTES
# ============================================================

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Pet Passport Vet AHC Generator", "version": "2.1"})



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

        pdf_bytes = fill_ahc_bytes(data)

        owner = data.get("owner_name", "unknown").replace(" ", "_")
        pet = data.get("pet_name", "pet").replace(" ", "_")
        filename = f"AHC_{owner}_{pet}.pdf"

        return send_file(
            pdf_bytes,
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
