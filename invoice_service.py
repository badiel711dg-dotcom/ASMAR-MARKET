import os
import html
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image,
    Table, TableStyle, LongTable, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

import arabic_reshaper
from bidi.algorithm import get_display


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(BASE_DIR, "static", "images", "moder-one-logo.png")
FONT_DIR = os.path.join(BASE_DIR, "static", "fonts", "moder-one")

IVORY = colors.HexColor("#F8F5EF")
CHARCOAL = colors.HexColor("#292629")
GOLD = colors.HexColor("#B99A62")
PALE_GOLD = colors.HexColor("#F3EBDD")
WINE = colors.HexColor("#704653")
MUTED = colors.HexColor("#817A75")
LINE = colors.HexColor("#E8E0D6")


def _register_fonts():
    if "MOArabic" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(
            TTFont("MOArabic", os.path.join(FONT_DIR, "almarai-400.ttf"))
        )
    if "MOArabicBold" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(
            TTFont("MOArabicBold", os.path.join(FONT_DIR, "almarai-700.ttf"))
        )
    if "MOEnglish" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(
            TTFont("MOEnglish", os.path.join(FONT_DIR, "inter-400.ttf"))
        )
    if "MOEnglishBold" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(
            TTFont("MOEnglishBold", os.path.join(FONT_DIR, "inter-700.ttf"))
        )


def _safe(value):
    return html.escape(str(value if value is not None else ""))


def _ar(value):
    value = str(value if value is not None else "")
    return get_display(arabic_reshaper.reshape(value))


def _money(value, currency):
    try:
        number = float(value or 0)
        formatted = f"{number:,.2f}".rstrip("0").rstrip(".")
    except (ValueError, TypeError):
        formatted = str(value or "0")
    return f"{formatted} {_safe(currency or 'YER')}"


def _paragraph(text, style):
    return Paragraph(text, style)


def build_invoice_pdf(snapshot, output_path, logo_path=None):
    """
    إنشاء فاتورة PDF ثنائية اللغة من لقطة بيانات ثابتة.
    لا يتصل هذا المحرك بقاعدة البيانات ولا يغير بيانات الطلب.
    """
    if not isinstance(snapshot, dict):
        raise ValueError("Invoice snapshot must be a dictionary")

    _register_fonts()

    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=17 * mm,
        leftMargin=17 * mm,
        topMargin=17 * mm,
        bottomMargin=19 * mm,
        title=f"MODER ONE Invoice {snapshot.get('invoice_number', '')}",
        author="MODER ONE",
        subject="Bilingual Merchant Invoice",
        allowSplitting=1,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "MOTitle", parent=styles["Title"],
        fontName="MOEnglishBold", fontSize=21,
        leading=27, textColor=CHARCOAL,
        alignment=TA_CENTER, spaceAfter=3 * mm,
    )

    subtitle_style = ParagraphStyle(
        "MOSubtitle", parent=styles["Normal"],
        fontName="MOArabicBold", fontSize=13,
        leading=20, textColor=WINE,
        alignment=TA_CENTER, spaceAfter=2 * mm,
    )

    section_style = ParagraphStyle(
        "MOSection", parent=styles["Heading2"],
        fontName="MOArabicBold", fontSize=11,
        leading=17, textColor=CHARCOAL,
        alignment=TA_RIGHT, spaceBefore=4 * mm,
        spaceAfter=2 * mm,
    )

    arabic_style = ParagraphStyle(
        "MOArabic", parent=styles["Normal"],
        fontName="MOArabic", fontSize=9,
        leading=15, textColor=CHARCOAL,
        alignment=TA_RIGHT,
    )

    arabic_bold_style = ParagraphStyle(
        "MOArabicBoldStyle", parent=arabic_style,
        fontName="MOArabicBold",
    )

    english_style = ParagraphStyle(
        "MOEnglish", parent=styles["Normal"],
        fontName="MOEnglish", fontSize=8,
        leading=12, textColor=MUTED,
        alignment=TA_LEFT,
    )

    english_bold_style = ParagraphStyle(
        "MOEnglishBold", parent=english_style,
        fontName="MOEnglishBold", textColor=CHARCOAL,
    )

    table_ar = ParagraphStyle(
        "MOTableArabic", parent=arabic_style,
        fontSize=8, leading=12,
    )

    table_en = ParagraphStyle(
        "MOTableEnglish", parent=english_style,
        fontSize=7, leading=10,
    )

    story = []

    if logo_path and os.path.isfile(logo_path):
        try:
            from io import BytesIO
            from PIL import Image as PILImage

            with PILImage.open(logo_path) as source:
                source.load()
                source.thumbnail((700, 700), PILImage.Resampling.LANCZOS)
                optimized_logo = BytesIO()
                source.save(
                    optimized_logo,
                    format="PNG",
                    optimize=True,
                    compress_level=9,
                )
                optimized_logo.seek(0)

            width, height = ImageReader(optimized_logo).getSize()
            if width > 0 and height > 0:
                logo_width = 39 * mm
                logo_height = logo_width * height / width
                logo = Image(
                    optimized_logo,
                    width=logo_width,
                    height=logo_height,
                )
                logo.hAlign = "CENTER"
                story.extend([logo, Spacer(1, 3 * mm)])
        except Exception as exc:
            raise RuntimeError("Invoice branding logo could not be processed") from exc

    story.append(_paragraph("MODER ONE", title_style))
    story.append(_paragraph(_ar("فاتورة المتجر"), subtitle_style))
    story.append(_paragraph("MERCHANT INVOICE", english_bold_style))
    story.append(Spacer(1, 3 * mm))
    story.append(HRFlowable(
        width="100%", thickness=1.2,
        color=GOLD, spaceBefore=1 * mm, spaceAfter=4 * mm
    ))

    invoice_number = _safe(snapshot.get("invoice_number", ""))
    issue_date = _safe(snapshot.get("issued_at", ""))
    currency = snapshot.get("currency") or "YER"

    def info_cell(ar_label, en_label, value):
        return [
            _paragraph(_ar(ar_label), arabic_bold_style),
            _paragraph(en_label, english_style),
            _paragraph(_safe(value) or "—", english_bold_style),
        ]

    merchant = snapshot.get("merchant") or {}
    customer = snapshot.get("customer") or {}

    meta_data = [
        [
            info_cell("رقم الفاتورة", "INVOICE NUMBER", invoice_number),
            info_cell("تاريخ الإصدار", "ISSUE DATE", issue_date),
        ],
        [
            info_cell("المتجر", "STORE", merchant.get("name", "")),
            info_cell("هاتف المتجر", "STORE PHONE", merchant.get("phone", "")),
        ],
    ]

    meta_table = Table(meta_data, colWidths=[88 * mm, 88 * mm])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), IVORY),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(meta_table)

    story.append(_paragraph(
        _ar("بيانات العميل") + "  |  CUSTOMER DETAILS",
        section_style
    ))

    customer_rows = [
        [
            _paragraph(_ar("اسم العميل"), table_ar),
            _paragraph(_safe(customer.get("name", "")) or "—", table_en),
            _paragraph(_ar("رقم الهاتف"), table_ar),
            _paragraph(_safe(customer.get("phone", "")) or "—", table_en),
        ],
        [
            _paragraph(_ar("العنوان"), table_ar),
            _paragraph(_safe(customer.get("address", "")) or "—", table_en),
            _paragraph(_ar("المدينة"), table_ar),
            _paragraph(_safe(customer.get("city", "")) or "—", table_en),
        ],
    ]

    customer_table = Table(
        customer_rows,
        colWidths=[25 * mm, 63 * mm, 25 * mm, 63 * mm]
    )
    customer_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(customer_table)

    story.append(_paragraph(
        _ar("تفاصيل المنتجات") + "  |  PRODUCTS DETAILS",
        section_style
    ))

    header = [
        _paragraph(_ar("رقم الصنف") + "<br/>ITEM ID", table_ar),
        _paragraph(_ar("اسم الصنف") + "<br/>PRODUCT NAME", table_ar),
        _paragraph(_ar("الكمية") + "<br/>QTY", table_ar),
        _paragraph(_ar("سعر الوحدة") + "<br/>UNIT PRICE", table_ar),
        _paragraph(_ar("الإجمالي") + "<br/>TOTAL", table_ar),
    ]

    product_rows = [header]
    items = snapshot.get("items") or []

    for item in items:
        quantity = item.get("quantity", 0)
        price = item.get("price", 0)
        try:
            line_total = float(price or 0) * float(quantity or 0)
        except (ValueError, TypeError):
            line_total = 0

        product_id = item.get("product_id")
        product_name = str(item.get("name", item.get("product_name", "")))
        product_rows.append([
            _paragraph(_safe(product_id if product_id is not None else "—"), table_en),
            _paragraph(_ar(product_name), table_ar),
            _paragraph(_safe(quantity), table_en),
            _paragraph(_money(price, currency), table_en),
            _paragraph(_money(line_total, currency), table_en),
        ])

    if not items:
        product_rows.append([
            _paragraph("—", table_en),
            _paragraph("—", table_ar),
            _paragraph("0", table_en),
            _paragraph("—", table_en),
            _paragraph("—", table_en),
        ])

    products_table = LongTable(
        product_rows,
        colWidths=[22 * mm, 56 * mm, 18 * mm, 32 * mm, 32 * mm],
        repeatRows=1,
        hAlign="LEFT",
    )
    products_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALE_GOLD),
        ("TEXTCOLOR", (0, 0), (-1, 0), CHARCOAL),
        ("BOX", (0, 0), (-1, -1), 0.7, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.45, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, IVORY]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(products_table)

    story.append(_paragraph(
        _ar("ملخص الحساب") + "  |  FINANCIAL SUMMARY",
        section_style
    ))

    financials = [
        ("مجموع المنتجات", "SUBTOTAL", snapshot.get("subtotal", 0)),
        ("خصم الكوبون", "COUPON DISCOUNT", snapshot.get("coupon_discount", 0)),
        ("تكلفة الشحن", "SHIPPING", snapshot.get("shipping_cost", 0)),
        ("الإجمالي النهائي", "GRAND TOTAL", snapshot.get("total", 0)),
    ]

    financial_rows = []
    for ar_label, en_label, amount in financials:
        financial_rows.append([
            _paragraph(_ar(ar_label), table_ar),
            _paragraph(en_label, table_en),
            _paragraph(_money(amount, currency), english_bold_style),
        ])

    financial_table = Table(
        financial_rows,
        colWidths=[70 * mm, 55 * mm, 51 * mm]
    )
    financial_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -2), IVORY),
        ("BACKGROUND", (0, -1), (-1, -1), PALE_GOLD),
        ("BOX", (0, 0), (-1, -1), 0.7, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(financial_table)

    payment = snapshot.get("payment_method", "")
    story.append(Spacer(1, 3 * mm))
    story.append(_paragraph(
        _ar("طريقة الدفع") + "  |  PAYMENT METHOD: " + _safe(payment or "—"),
        arabic_style
    ))

    policy_ar = str(snapshot.get("return_policy") or "").strip()
    policy_en = str(snapshot.get("return_policy_en") or "").strip()

    if policy_ar or policy_en:
        story.append(_paragraph(
            _ar("سياسة الاسترجاع والضمان") + "  |  RETURN & WARRANTY POLICY",
            section_style
        ))

        if policy_ar:
            story.append(_paragraph(
                _ar("السياسة باللغة العربية"),
                arabic_bold_style
            ))
            story.append(_paragraph(_ar(policy_ar), arabic_style))

        if policy_en:
            story.append(Spacer(1, 2 * mm))
            story.append(_paragraph(
                "POLICY IN ENGLISH",
                english_bold_style
            ))
            story.append(_paragraph(policy_en, english_style))

    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(
        width="100%", thickness=0.7,
        color=LINE, spaceBefore=2 * mm, spaceAfter=3 * mm
    ))
    story.append(_paragraph(
        _ar("شكراً لثقتكم وتسوقكم من متجرنا") ,
        ParagraphStyle(
            "MOThanksAR", parent=subtitle_style,
            fontSize=11, leading=17, spaceAfter=2 * mm
        )
    ))
    story.append(_paragraph(
        "THANK YOU FOR SHOPPING WITH US",
        ParagraphStyle(
            "MOThanksEN", parent=english_style,
            alignment=TA_CENTER, fontName="MOEnglishBold",
            textColor=WINE, fontSize=9
        )
    ))

    def page_footer(canvas, document):
        canvas.saveState()
        page_width, _ = A4
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(17 * mm, 13 * mm, page_width - 17 * mm, 13 * mm)
        canvas.setFont("MOEnglish", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(17 * mm, 8 * mm, "MODER ONE")
        canvas.drawRightString(
            page_width - 17 * mm, 8 * mm,
            f"PAGE {document.page}"
        )
        canvas.restoreState()

    doc.build(
        story,
        onFirstPage=page_footer,
        onLaterPages=page_footer,
    )

    if not os.path.isfile(output_path) or os.path.getsize(output_path) < 1000:
        raise RuntimeError("Invoice PDF generation failed")

    return output_path
