"""Detect formulas saved without their results (2026-11-09).

Excel stores each formula together with its last result (`<f>E2*F2</f><v>8256</v>`), and
every reader here reads that stored result. A workbook saved by a library such as openpyxl
keeps the formula but writes an empty result (`<f>E2*F2</f><v></v>`); the readers then see
blank cells, and the sync stored RSU amounts of ¥0, blank quantities and a ¥0 gold value.

`uncached_formula_cells` finds those cells by reading the sheet XML directly (fast, no
formula evaluation). A formula whose result really is an empty string is not flagged: Excel
marks it `t="str"`. The fix for the owner is always the same: open the file in Excel,
recalculate, save, upload again.
"""
from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from xml.etree import ElementTree as ET

_MAIN = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
_REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
_PKG_REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'
EXCEL_SUFFIXES = {'.xlsx', '.xlsm'}
MAX_LISTED = 5


class UncachedFormulasError(ValueError):
    """A workbook holds formulas with no saved result; reading it would give blanks."""


def _sheet_parts(z: zipfile.ZipFile) -> Dict[str, str]:
    """Sheet name → part path inside the package."""
    rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
    targets = {r.get('Id'): r.get('Target', '') for r in rels.iter(f'{_PKG_REL}Relationship')}
    parts = {}
    for sheet in ET.fromstring(z.read('xl/workbook.xml')).iter(f'{_MAIN}sheet'):
        target = targets.get(sheet.get(f'{_REL}id'), '')
        parts[sheet.get('name')] = target.lstrip('/') if target.startswith('/') else posixpath.normpath(
            posixpath.join('xl', target))
    return parts


def uncached_formula_cells(path: Path | str, sheets: Optional[Iterable[str]] = None) -> Dict[str, List[str]]:
    """Return {sheet name: [cell refs]} of formulas with no saved result.

    `sheets` limits the check to those sheet names (missing names are ignored: the reader
    reports a missing sheet itself). Not an xlsx/xlsm package
    (e.g. legacy .xls) → {}: the format check owns that.
    """
    path = Path(path)
    wanted = None if sheets is None else set(sheets)
    found: Dict[str, List[str]] = {}
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        return {}
    with z:
        try:
            parts = _sheet_parts(z)
        except (KeyError, ET.ParseError):
            return {}
        for name, part in parts.items():
            if (wanted is not None and name not in wanted) or part not in z.namelist():
                continue
            cells: List[str] = []
            with z.open(part) as fh:
                for _, el in ET.iterparse(fh):
                    if el.tag != f'{_MAIN}c':
                        continue
                    if el.find(f'{_MAIN}f') is not None and el.get('t') != 'str':
                        v = el.find(f'{_MAIN}v')
                        if v is None or not (v.text or '').strip():
                            cells.append(el.get('r') or '?')
                    el.clear()
            if cells:
                found[name] = cells
    return found


def describe(file_name: str, found: Dict[str, List[str]]) -> str:
    """One plain message for the owner, naming the file, sheets and first cells."""
    total = sum(len(c) for c in found.values())
    where = '; '.join(f"{sheet}: {', '.join(cells[:MAX_LISTED])}{' …' if len(cells) > MAX_LISTED else ''}"
                      for sheet, cells in found.items())
    return (f"{file_name}: {total} formula cell(s) have no saved result ({where}). "
            "The file was saved by a program that does not calculate formulas. "
            "Open it in Excel, recalculate (Cmd+= / F9), save, and upload it again.")


def assert_formulas_cached(path: Path | str, sheets: Optional[Iterable[str]] = None) -> None:
    """Raise UncachedFormulasError when `path` holds formulas with no saved result."""
    found = uncached_formula_cells(path, sheets)
    if found:
        raise UncachedFormulasError(describe(Path(path).name, found))
