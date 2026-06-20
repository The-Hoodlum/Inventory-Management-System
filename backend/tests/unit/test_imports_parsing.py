"""File parsing for csv / xlsx / xls. xlsx/xls skip if the optional wheel is absent."""
from __future__ import annotations

import io

import pytest

from app.imports.domain.parsing import UnsupportedFileType, parse_table


def test_csv_headers_and_rows():
    data = b"SKU,Name,Qty\nA-1,Widget,10\nA-2,Gadget,5\n"
    table = parse_table("stock.csv", data)
    assert table.headers == ["SKU", "Name", "Qty"]
    assert table.rows == [["A-1", "Widget", "10"], ["A-2", "Gadget", "5"]]


def test_csv_strips_bom_and_blank_rows():
    data = "﻿SKU,Name\nA-1,Widget\n\n,\nA-2,Gadget\n".encode()
    table = parse_table("stock.csv", data)
    assert table.headers == ["SKU", "Name"]
    assert table.rows == [["A-1", "Widget"], ["A-2", "Gadget"]]


def test_unsupported_extension():
    with pytest.raises(UnsupportedFileType):
        parse_table("stock.pdf", b"whatever")


def test_xlsx_roundtrip():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["SKU", "Name", "Qty"])
    ws.append(["A-1", "Widget", 10])      # int cell -> "10", not "10.0"
    ws.append(["A-2", "Gadget", 5.0])
    buf = io.BytesIO()
    wb.save(buf)
    table = parse_table("stock.xlsx", buf.getvalue())
    assert table.headers == ["SKU", "Name", "Qty"]
    assert table.rows == [["A-1", "Widget", "10"], ["A-2", "Gadget", "5"]]


def test_xls_roundtrip():
    xlwt = pytest.importorskip("xlwt")  # only to *write* a fixture; reading uses xlrd
    pytest.importorskip("xlrd")
    book = xlwt.Workbook()
    sheet = book.add_sheet("s")
    for r, row in enumerate([["SKU", "Name", "Qty"], ["A-1", "Widget", 10]]):
        for c, val in enumerate(row):
            sheet.write(r, c, val)
    buf = io.BytesIO()
    book.save(buf)
    table = parse_table("stock.xls", buf.getvalue())
    assert table.headers == ["SKU", "Name", "Qty"]
    assert table.rows == [["A-1", "Widget", "10"]]
