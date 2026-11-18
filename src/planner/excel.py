"""Excel report pack: summary, data quality, country KPIs, city pairs, opportunities, changelog."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER = PatternFill("solid", fgColor="0B3D6E")
WHITE = Font(color="FFFFFF", bold=True)


def _style(ws, df: pd.DataFrame) -> None:
    for i, col in enumerate(df.columns, 1):
        c = ws.cell(row=1, column=i)
        c.fill, c.font, c.alignment = HEADER, WHITE, Alignment(vertical="center", wrap_text=True)
        width = max([len(str(col))] + [len(str(v)) for v in df[col].head(200)]) + 2
        ws.column_dimensions[get_column_letter(i)].width = min(max(width, 8), 48)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.row_dimensions[1].height = 30


def write_excel(path: Path, sheets: dict[str, pd.DataFrame]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            _style(xw.sheets[name[:31]], df)
    return path
