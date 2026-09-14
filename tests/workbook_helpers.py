"""Shared reader for the tracked normalized workbook schema contract."""

from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile


def workbook_definitions(table_names):
    """Read the tracked authoritative contract without adding a dependency."""
    path = Path(__file__).resolve().parents[1] / "docs/reference/RHU_LabChain_Improved_3NF_Normalization(1).xlsx"
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    definitions = {}
    with ZipFile(path) as workbook:
        strings = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            strings = ["".join(e.itertext()) for e in ET.fromstring(
                workbook.read("xl/sharedStrings.xml")).findall("m:si", ns)]
        rels = {e.attrib["Id"]: e.attrib["Target"] for e in ET.fromstring(
            workbook.read("xl/_rels/workbook.xml.rels"))}
        for sheet in ET.fromstring(workbook.read("xl/workbook.xml")).findall("m:sheets/m:sheet", ns):
            name = sheet.attrib["name"].lower()
            if name not in table_names:
                continue
            target = rels[sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]
            target = target.lstrip("/") if target.startswith("/") else "xl/" + target
            columns = []
            for row in ET.fromstring(workbook.read(target)).findall("m:sheetData/m:row", ns):
                cells = {}
                for cell in row.findall("m:c", ns):
                    value = cell.find("m:v", ns)
                    inline = cell.find("m:is", ns)
                    value = value.text if value is not None else "".join(inline.itertext()) if inline is not None else ""
                    if cell.attrib.get("t") == "s":
                        value = strings[int(value)]
                    letter = "".join(c for c in cell.attrib["r"] if c.isalpha())
                    cells[letter] = value
                if cells.get("B") in {"BIGINT", "VARCHAR", "TEXT", "DATETIME", "ENUM", "DECIMAL", "BOOLEAN", "CHAR", "INT", "DATE", "JSON"}:
                    columns.append(tuple(cells.get(letter, "") for letter in "ABCDEF"))
            definitions[name] = columns
    assert set(definitions) == set(table_names)
    return definitions

