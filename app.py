"""
Pet Passport Vet - AHC PDF Generation Web Service
v5.1 - Minimal-touch + viewer-proof strikethroughs.
       Fills only pet/owner-specific data; Quentin's practice details and
       checkboxes are left to the template.
       The template's strikethroughs are stored as fragile orphan widget
       annotations (no field type/value), which strict viewers (Acrobat,
       Mac Preview) drop when they regenerate form appearances. To make them
       viewer-independent, v5.1 re-draws every strike as permanent page
       content (via merge_page) and removes the original strike widgets.
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
#
# IMPORTANT (v5.0): This now fills ONLY pet/owner-specific data.
# The following are baked into the template and deliberately NOT set here,
# so the app never overwrites Quentin's saved working file:
#   - Practice details: LCA, OV name, OV qualification, OV address,
#     OV telephone, Placedate
#   - All checkboxes: Check 2,3,5,6,7,8,9,10,13,14,16,19,20
#   - All strikethroughs (these live in the page content, not form fields)
#
# Text1 / Text13 remain excluded (Text1 handled via stamp; Text13 unused).
# Commodity description2 (I.28) and Text5 are handled via AP streams below.
# ============================================================

def get_field_values(d):
    qty = int(d.get("pet_quantity", 1))
    return [
        {"field_id": "Name1",                  "value": d.get("owner_name", "")},
        {"field_id": "Address1",               "value": format_address(d.get("owner_address", ""))},
        {"field_id": "Telephone1",             "value": d.get("owner_telephone", "")},
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
        {"field_id": "Date",         "value": d.get("issue_date", "")},
        {"field_id": "Transponder",  "value": d.get("pet_microchip", "")},
        {"field_id": "AHC number",   "value": d.get("ahc_number", "")},
        {"field_id": "AHC number1",  "value": d.get("ahc_number", "") if qty >= 2 else ""},
        {"field_id": "AHC number2",  "value": d.get("ahc_number", "") if qty >= 3 else ""},
        {"field_id": "AHC number3",  "value": d.get("ahc_number", "") if qty >= 4 else ""},
        {"field_id": "AHC number4",  "value": d.get("ahc_number", "") if qty >= 5 else ""},
    ]


# ============================================================
# FILL THE AHC PDF
# ============================================================

def fill_ahc_bytes(data):
    reader = PdfReader(TEMPLATE_PATH)
    writer = PdfWriter()
    writer.append(reader)

    # Standard field updates — pet/owner-specific data only.
    updates = {fv["field_id"]: fv["value"] for fv in get_field_values(data)}
    for page in writer.pages:
        writer.update_page_form_field_values(page, updates, auto_regenerate=False)

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

    # Make strikethroughs viewer-proof: redraw as page content, then drop the
    # fragile widget annotations that strict viewers would otherwise regenerate.
    bake_strikethroughs(writer)
    remove_strike_widgets(writer)

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
# STRIKETHROUGHS — viewer-proof baking
#
# Each (x0, y, x1) is a horizontal strike segment in PDF points (origin
# bottom-left), captured from the template's strike widgets. We redraw these
# as real page content so no viewer can drop them, then delete the original
# thin-line widget annotations. If the template's strike layout ever changes,
# re-run the extraction script to regenerate this table.
# ============================================================

STRIKE_SEGMENTS = {
    2: [
        (145.21, 445.64, 256.45), (141.35, 433.19, 544.96), (142.83, 422.79, 544.44),
        (141.74, 412.39, 404.88), (142.36, 400.32, 545.46), (143.79, 390.46, 545.98),
        (141.89, 379.12, 400.22), (109.41, 355.08, 545.97), (142.31, 344.91, 297.81),
        (112.09, 331.67, 548.65), (141.72, 321.21, 547.51), (141.8, 311.21, 508.21),
        (141.13, 298.5, 546.92), (140.78, 288.78, 546.58), (141.08, 278.37, 546.87),
        (140.7, 267.86, 244.99), (141.33, 255.89, 372.36), (141.55, 243.18, 517.6),
        (129.9, 208.39, 545.84), (133.0, 198.03, 545.44), (133.12, 187.95, 545.24),
        (133.11, 177.1, 545.55), (133.22, 167.06, 545.13), (132.75, 156.33, 545.44),
        (134.15, 146.25, 545.2), (132.91, 135.78, 252.78),
    ],
    3: [
        (132.68, 626.76, 546.44), (168.29, 616.33, 545.83), (168.42, 606.29, 545.92),
        (168.4, 595.4, 545.94), (168.51, 585.4, 546.1), (168.05, 574.74, 545.82),
        (168.21, 564.52, 245.09), (169.89, 552.9, 548.95), (168.11, 539.82, 547.07),
        (168.75, 529.4, 547.6), (168.0, 518.49, 547.17), (167.94, 508.89, 547.0),
        (167.42, 486.63, 546.48), (168.78, 475.58, 547.84), (168.72, 466.41, 547.78),
        (168.66, 455.63, 547.72), (168.6, 445.65, 365.48), (162.2, 432.36, 546.06),
        (166.37, 421.82, 547.18), (165.49, 411.24, 546.3), (166.64, 401.3, 547.45),
        (165.78, 390.88, 546.59), (165.72, 380.1, 546.53), (165.66, 370.96, 546.47),
        (166.48, 360.0, 547.29), (166.35, 349.78, 269.34), (164.62, 337.61, 548.48),
        (164.37, 327.04, 548.23), (165.29, 316.27, 549.16), (165.05, 305.7, 548.91),
        (165.36, 296.43, 549.22), (165.11, 285.86, 548.97), (166.04, 275.08, 549.9),
        (165.79, 264.51, 549.65), (166.31, 254.61, 550.18), (167.24, 243.91, 548.49),
        (166.99, 233.26, 497.48), (164.21, 221.59, 548.08), (164.77, 211.42, 548.63),
        (164.09, 200.44, 547.96), (164.65, 190.28, 548.51), (165.36, 180.1, 549.22),
        (165.91, 169.93, 549.78), (165.23, 158.96, 549.1), (165.79, 148.79, 549.65),
        (165.47, 138.08, 549.33), (166.02, 127.91, 549.88), (166.73, 117.69, 548.09),
        (167.29, 107.57, 547.22), (166.61, 96.6, 546.54), (167.16, 86.48, 547.1),
    ],
    4: [
        (167.47, 653.16, 546.97), (167.33, 642.19, 546.29), (167.78, 631.98, 350.46),
        (131.22, 355.56, 546.5), (131.5, 344.99, 546.78), (131.71, 334.22, 546.99),
        (131.99, 323.64, 547.27), (132.51, 314.52, 547.79), (132.79, 303.94, 548.08),
        (133.0, 292.99, 548.28), (132.95, 282.85, 196.21), (130.98, 270.39, 546.26),
        (129.39, 259.23, 437.62),
    ],
    9: [
        (75.62, 693.93, 108.97), (103.79, 693.08, 524.18), (74.98, 679.99, 144.35),
        (163.92, 679.59, 217.02), (207.97, 679.12, 518.86), (189.82, 666.28, 392.86),
        (284.22, 627.88, 323.58), (315.74, 628.14, 525.33), (70.3, 614.12, 481.71),
        (149.89, 575.26, 232.12), (220.37, 575.01, 526.76), (70.42, 561.84, 328.24),
        (142.1, 370.53, 293.17), (143.23, 351.97, 524.97), (142.69, 338.7, 524.42),
        (142.98, 325.85, 524.72), (141.87, 312.6, 172.99), (140.91, 293.36, 522.64),
        (142.95, 279.67, 524.69), (141.12, 266.84, 522.86), (143.17, 253.44, 524.4),
        (142.02, 239.92, 206.22), (130.45, 199.83, 189.77), (179.74, 199.47, 525.12),
        (68.7, 185.76, 345.27), (414.44, 185.56, 498.31), (486.31, 185.72, 524.17),
        (70.6, 172.84, 524.77), (69.9, 159.63, 124.0),
    ],
}


def bake_strikethroughs(writer):
    """Draw every strike segment as permanent page content via a merged overlay."""
    for page_num, segments in STRIKE_SEGMENTS.items():
        if page_num > len(writer.pages):
            continue
        page = writer.pages[page_num - 1]
        pw = float(page.mediabox.width)
        ph = float(page.mediabox.height)

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(pw, ph))
        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(0.8)
        for x0, y, x1 in segments:
            c.line(x0, y, x1, y)
        c.save()
        buf.seek(0)

        overlay_page = PdfReader(buf).pages[0]
        page.merge_page(overlay_page)


def remove_strike_widgets(writer):
    """
    Delete the original thin-line strike widget annotations on the strike pages,
    so the only thing drawing those lines is the baked page content. This makes
    the strikes immune to form-appearance regeneration in strict viewers.
    """
    for page_num in STRIKE_SEGMENTS:
        if page_num > len(writer.pages):
            continue
        page = writer.pages[page_num - 1]
        annots = page.get('/Annots')
        if not annots:
            continue
        kept = ArrayObject()
        for a in annots.get_object():
            o = a.get_object()
            rect = [float(x) for x in o.get('/Rect', [0, 0, 0, 0])]
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
            is_strike_widget = (o.get('/Subtype') == '/Widget' and h < 2 and w > 30)
            if not is_strike_widget:
                kept.append(a)
        page[NameObject('/Annots')] = kept

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
    return jsonify({"status": "ok", "service": "Pet Passport Vet AHC Generator", "version": "5.1"})


@app.route("/debug", methods=["GET"])
def debug():
    test = {"pet_species": "CANIS LUPUS FAMILIARIS", "pet_sex": "MALE",
            "pet_colour": "BLACK", "pet_breed": "LABRADOR",
            "pet_microchip": "958000080144977", "pet_dob": "17/03/2023"}
    return jsonify({"i28_field": build_commodity_description2(test), "version": "5.1"})


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
