"""
PDF Export utilities for RupeeRoute using ReportLab.
Produces clean, formatted A4 PDF reports for Personal Tracker, Room/Trip Sharing,
Category Popups, and Lend & Borrow records.
"""
import io
import os
import datetime
from xml.sax.saxutils import escape

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


_FONTS_REGISTERED = False
_FONT_REGULAR = 'Helvetica'
_FONT_BOLD = 'Helvetica-Bold'
_CURRENCY_SYMBOL = 'Rs.'


def _ensure_fonts_registered():
    """Registers Windows TrueType fonts with Rupee (₹) glyph support once."""
    global _FONTS_REGISTERED, _FONT_REGULAR, _FONT_BOLD, _CURRENCY_SYMBOL
    if _FONTS_REGISTERED:
        return

    _FONTS_REGISTERED = True
    candidates = [
        ('RupeeArial', r'C:\Windows\Fonts\arial.ttf', 'RupeeArialBold', r'C:\Windows\Fonts\arialbd.ttf'),
        ('RupeeSegoe', r'C:\Windows\Fonts\segoeui.ttf', 'RupeeSegoeBold', r'C:\Windows\Fonts\segoeuib.ttf'),
        ('RupeeCalibri', r'C:\Windows\Fonts\calibri.ttf', 'RupeeCalibriBold', r'C:\Windows\Fonts\calibrib.ttf'),
    ]

    for reg_name, reg_path, bold_name, bold_path in candidates:
        if os.path.exists(reg_path):
            try:
                f_reg = TTFont(reg_name, reg_path)
                if 0x20B9 in f_reg.face.charToGlyph:
                    pdfmetrics.registerFont(f_reg)
                    _FONT_REGULAR = reg_name
                    if os.path.exists(bold_path):
                        f_bold = TTFont(bold_name, bold_path)
                        if 0x20B9 in f_bold.face.charToGlyph:
                            pdfmetrics.registerFont(f_bold)
                            _FONT_BOLD = bold_name
                        else:
                            _FONT_BOLD = reg_name
                    else:
                        _FONT_BOLD = reg_name
                    _CURRENCY_SYMBOL = '₹'
                    return
            except Exception:
                continue


def format_inr(amount):
    """Formats a Decimal/numeric amount safely with supported currency glyph."""
    _ensure_fonts_registered()
    try:
        val = float(amount or 0)
    except (ValueError, TypeError):
        val = 0.0
    return f"{_CURRENCY_SYMBOL}{val:,.2f}"


def sanitize_pdf_text(text):
    """Replaces ₹ if TTF font wasn't registered and XML-escapes for ReportLab Paragraph."""
    _ensure_fonts_registered()
    s = str(text or '')
    if _CURRENCY_SYMBOL != '₹':
        s = s.replace('₹', _CURRENCY_SYMBOL)
    return escape(s)


def build_pdf_response(
    filename,
    title,
    subtitle,
    columns,
    rows,
    col_widths=None,
    right_align_cols=None,
    summary_cells=None,
    use_landscape=False,
    accent_hex='#4f46e5',
):
    """
    Generates a downloadable ReportLab PDF response with unified RupeeRoute styling.

    - columns: list of header strings
    - rows: list of row iterables (matching len(columns))
    - col_widths: optional list of widths in points/mm (defaults to auto-distributed page width)
    - right_align_cols: set/list of 0-based column indices to right-align
    - summary_cells: optional single list/tuple for bottom bold total row
    """
    _ensure_fonts_registered()
    right_cols = set(right_align_cols or [])

    page_size = landscape(A4) if use_landscape else A4
    margin_x = 14 * mm
    margin_y = 14 * mm
    usable_width = page_size[0] - (2 * margin_x)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=margin_x,
        rightMargin=margin_x,
        topMargin=margin_y,
        bottomMargin=margin_y,
        title=f"RupeeRoute - {title}",
    )

    styles = getSampleStyleSheet()
    brand_style = ParagraphStyle(
        'RupeeBrand',
        parent=styles['Normal'],
        fontName=_FONT_BOLD,
        fontSize=9,
        textColor=colors.HexColor(accent_hex),
        leading=12,
    )
    title_style = ParagraphStyle(
        'RupeeTitle',
        parent=styles['Heading1'],
        fontName=_FONT_BOLD,
        fontSize=16,
        textColor=colors.HexColor('#0f172a'),
        spaceBefore=2,
        spaceAfter=3,
        leading=20,
    )
    subtitle_style = ParagraphStyle(
        'RupeeSubtitle',
        parent=styles['Normal'],
        fontName=_FONT_REGULAR,
        fontSize=9,
        textColor=colors.HexColor('#475569'),
        leading=13,
    )
    th_left = ParagraphStyle(
        'THLeft', fontName=_FONT_BOLD, fontSize=8.5, textColor=colors.white, alignment=TA_LEFT, leading=11
    )
    th_right = ParagraphStyle(
        'THRight', fontName=_FONT_BOLD, fontSize=8.5, textColor=colors.white, alignment=TA_RIGHT, leading=11
    )
    td_left = ParagraphStyle(
        'TDLeft', fontName=_FONT_REGULAR, fontSize=8.2, textColor=colors.HexColor('#1e293b'), alignment=TA_LEFT, leading=11
    )
    td_right = ParagraphStyle(
        'TDRight', fontName=_FONT_BOLD, fontSize=8.2, textColor=colors.HexColor('#0f172a'), alignment=TA_RIGHT, leading=11
    )
    sum_left = ParagraphStyle(
        'SumLeft', fontName=_FONT_BOLD, fontSize=8.8, textColor=colors.HexColor('#0f172a'), alignment=TA_LEFT, leading=12
    )
    sum_right = ParagraphStyle(
        'SumRight', fontName=_FONT_BOLD, fontSize=8.8, textColor=colors.HexColor(accent_hex), alignment=TA_RIGHT, leading=12
    )

    story = []

    # Header Metadata Banner
    generated_at = datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')
    header_data = [[
        Paragraph(f"RUPEEROUTE &bull; FINANCIAL LEDGER EXPORT", brand_style),
        Paragraph(f"Generated: {escape(generated_at)}", ParagraphStyle(
            'GenAt', fontName=_FONT_REGULAR, fontSize=8, textColor=colors.HexColor('#64748b'), alignment=TA_RIGHT
        ))
    ]]
    header_tbl = Table(header_data, colWidths=[usable_width * 0.65, usable_width * 0.35])
    header_tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(header_tbl)
    story.append(Paragraph(sanitize_pdf_text(title), title_style))
    story.append(Paragraph(sanitize_pdf_text(subtitle), subtitle_style))
    story.append(Spacer(1, 5 * mm))

    # Build Table Data
    table_data = []
    header_row = [
        Paragraph(sanitize_pdf_text(col), th_right if idx in right_cols else th_left)
        for idx, col in enumerate(columns)
    ]
    table_data.append(header_row)

    if rows:
        for r in rows:
            row_cells = [
                Paragraph(sanitize_pdf_text(val), td_right if idx in right_cols else td_left)
                for idx, val in enumerate(r)
            ]
            table_data.append(row_cells)
    else:
        empty_row = [Paragraph("No matching records found for the selected filters.", td_left)] + [
            Paragraph("", td_left) for _ in range(len(columns) - 1)
        ]
        table_data.append(empty_row)

    has_summary = bool(summary_cells)
    if has_summary:
        sum_row = [
            Paragraph(sanitize_pdf_text(val), sum_right if idx in right_cols else sum_left)
            for idx, val in enumerate(summary_cells)
        ]
        table_data.append(sum_row)

    if col_widths:
        # Scale proportions to usable_width cleanly
        total_req = sum(col_widths)
        resolved_widths = [(w / total_req) * usable_width for w in col_widths]
    else:
        resolved_widths = [usable_width / len(columns)] * len(columns)

    table = Table(table_data, colWidths=resolved_widths, repeatRows=1)

    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(accent_hex)),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('LINEBELOW', (0, 0), (-1, 0), 1.2, colors.HexColor(accent_hex)),
    ]

    # Zebra striping for body rows
    body_end = len(table_data) - 1 if has_summary else len(table_data)
    for row_idx in range(1, body_end):
        bg = colors.HexColor('#f8fafc') if row_idx % 2 == 0 else colors.white
        style_cmds.append(('BACKGROUND', (0, row_idx), (-1, row_idx), bg))

    if has_summary:
        last_idx = len(table_data) - 1
        style_cmds.append(('BACKGROUND', (0, last_idx), (-1, last_idx), colors.HexColor('#eef2ff')))
        style_cmds.append(('LINEABOVE', (0, last_idx), (-1, last_idx), 1.2, colors.HexColor(accent_hex)))

    if not rows:
        style_cmds.append(('SPAN', (0, 1), (-1, 1)))
        style_cmds.append(('ALIGN', (0, 1), (-1, 1), 'CENTER'))

    table.setStyle(TableStyle(style_cmds))
    story.append(table)

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
