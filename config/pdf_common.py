"""Общие хелперы серверной генерации PDF (договор, чек возврата).

Вынесено из contract_pdf.py: поиск TTF-шрифта с кириллицей/латиницей,
форматирование денег, ленивый импорт fpdf2, диагональный водяной знак.
Чистый Python, без системных зависимостей.
"""
from decimal import Decimal
from pathlib import Path

from django.conf import settings

BASE_DIR = Path(settings.BASE_DIR)


class PdfFontMissing(RuntimeError):
    """Не найден ни один TTF-шрифт для PDF."""
    pass


class PdfDependencyMissing(RuntimeError):
    """Не установлен пакет fpdf2 — PDF собрать нечем."""
    pass


# Порядок поиска шрифта с поддержкой кириллицы и узбекской латиницы.
_FONT_CANDIDATES = [
    getattr(settings, 'CONTRACT_PDF_FONT_PATH', None),
    BASE_DIR / 'static' / 'fonts' / 'DejaVuSans.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/dejavu/DejaVuSans.ttf',
    '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
    '/Library/Fonts/Arial Unicode.ttf',
]
_BOLD_CANDIDATES = [
    getattr(settings, 'CONTRACT_PDF_FONT_BOLD_PATH', None),
    BASE_DIR / 'static' / 'fonts' / 'DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf',
]


def _first_existing(paths):
    for p in paths:
        if not p:
            continue
        p = Path(p)
        if p.is_file():
            return str(p)
    return None


def resolve_fonts():
    """Вернуть (regular_path, bold_path|None). Бросить PdfFontMissing, если
    не найден ни один обычный шрифт."""
    regular = _first_existing(_FONT_CANDIDATES)
    if not regular:
        raise PdfFontMissing(
            'Не найден TTF-шрифт для PDF. Положите static/fonts/DejaVuSans.ttf '
            'или установите системный (apt install fonts-dejavu-core), '
            'либо задайте CONTRACT_PDF_FONT_PATH.'
        )
    bold = _first_existing(_BOLD_CANDIDATES)
    return regular, bold


def load_fpdf():
    """Ленивый импорт fpdf2; PdfDependencyMissing, если пакет не установлен."""
    try:
        import fpdf as fpdf_module
    except ImportError as exc:
        raise PdfDependencyMissing(
            'Для генерации PDF требуется пакет fpdf2. '
            'Установите его в текущий Python-интерпретатор: '
            '`pip install fpdf2`.'
        ) from exc
    return fpdf_module


def money(value) -> str:
    """12345.60 -> "12 345.60" (пробел-разделитель тысяч, 2 знака)."""
    q = Decimal(value or 0).quantize(Decimal('0.01'))
    intpart, _, frac = f'{q:.2f}'.partition('.')
    neg = intpart.startswith('-')
    intpart = intpart.lstrip('-')
    groups = []
    while intpart:
        groups.insert(0, intpart[-3:])
        intpart = intpart[:-3]
    return ('-' if neg else '') + ' '.join(groups) + '.' + frac


# Параметры водяного знака (перенесены из contract_pdf без изменений).
_WATERMARK_GRAY = 205
_WATERMARK_TEXT = 'Raxmonov'
_WATERMARK_WIDTH_FACTOR = 0.9


def draw_watermark(pdf):
    """Бледный диагональный текстовый водяной знак по центру текущей страницы.

    Рисуется встроенным core-шрифтом Helvetica (ASCII), не зависит от
    загруженного TTF. ``pdf.rotation(...)`` восстанавливает цвет/шрифт сам;
    курсор возвращаем явно. Угол −30° согласован с HTML-печатью.
    """
    g = _WATERMARK_GRAY
    x0, y0 = pdf.get_x(), pdf.get_y()
    cx, cy = pdf.w / 2, pdf.h / 2
    target_w = min(pdf.w, pdf.h) * _WATERMARK_WIDTH_FACTOR

    with pdf.rotation(-30, cx, cy):
        pdf.set_text_color(g, g, g)
        pdf.set_font('Helvetica', 'B', 100)
        w100 = pdf.get_string_width(_WATERMARK_TEXT) or 1
        size = 100 * target_w / w100
        pdf.set_font('Helvetica', 'B', size)
        tw = pdf.get_string_width(_WATERMARK_TEXT)
        th = size * 0.3528  # pt → mm
        pdf.set_xy(cx - tw / 2, cy - th / 2)
        pdf.cell(tw, th, _WATERMARK_TEXT, align='C')

    pdf.set_xy(x0, y0)
