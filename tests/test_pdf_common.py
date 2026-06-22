"""Юнит-тесты общих PDF-хелперов (вынесены из contract_pdf)."""
from decimal import Decimal

from config import contract_pdf
from config.pdf_common import (
    PdfDependencyMissing,
    PdfFontMissing,
    money,
    resolve_fonts,
)


def test_money_groups_thousands():
    assert money(Decimal('12345.6')) == '12 345.60'
    assert money(0) == '0.00'
    assert money(Decimal('-1500')) == '-1 500.00'


def test_resolve_fonts_returns_regular_path():
    regular, bold = resolve_fonts()
    assert regular and isinstance(regular, str)
    assert bold is None or isinstance(bold, str)


def test_contract_aliases_point_to_common_exceptions():
    assert contract_pdf.ContractFontMissing is PdfFontMissing
    assert contract_pdf.ContractDependencyMissing is PdfDependencyMissing
