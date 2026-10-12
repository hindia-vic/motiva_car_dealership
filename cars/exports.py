import csv
import io

from django.http import HttpResponse


def stream_csv(filename, headers, rows):
    """Build an attachment response streaming the given rows as CSV"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return response


def stream_pdf(filename, title, headers, rows):
    """Build a downloadable PDF with a titled table of the given rows

    ReportLab is imported lazily (and only when a PDF is actually requested) so
    that a missing optional dependency can never prevent the rest of the site
    from loading.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle
    except ImportError:
        raise ImportError(
            "PDF export requires the 'reportlab' package. Install it with: "
            "pip install reportlab   (or in this project: uv add reportlab)"
        ) from None

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title=title,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'ReportTitle',
        parent=styles['Title'],
        fontSize=16,
        spaceAfter=6,
        textColor=colors.HexColor('#1a5f7a'),
    )
    header_style = ParagraphStyle(
        'ReportTableHeader',
        parent=styles['BodyText'],
        fontSize=9,
        fontName='Helvetica-Bold',
        textColor=colors.white,
    )
    meta_style = ParagraphStyle(
        'ReportMeta',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.grey,
        spaceAfter=12,
    )

    def _fmt(value):
        """Convert a cell value to safe, display-ready text"""
        if value is None:
            return ''
        return str(value)

    data = [[Paragraph(_safe(_fmt(header)), header_style) for header in headers]]
    for row in rows:
        data.append([Paragraph(_safe(_fmt(cell)), styles['BodyText']) for cell in row])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a5f7a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f2f6f8')]),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))

    story = [
        Paragraph(_safe(title), title_style),
        Paragraph('Generated report', meta_style),
        table,
    ]
    doc.build(story)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _safe(text):
    """Escape a few characters that break ReportLab paragraphs"""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')