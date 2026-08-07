from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

from ots_otd_app.database import DB_PATH, get_database_config
from ots_otd_app.time_utils import now_iso


def dataframe_to_excel(sheets: dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, df in sheets.items():
            sheet_name = str(name or "dados")[:31]
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    return output.getvalue()


def local_backup_zip(read_all_callback) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        df = read_all_callback()
        archive.writestr("ots_otd.xlsx", dataframe_to_excel({"ots_otd": df}))
        archive.writestr(
            "manifesto.json",
            (
                "{\n"
                f'  "gerado_em": "{now_iso()}",\n'
                f'  "tipo_banco": "{get_database_config().db_type}",\n'
                f'  "registros": {int(len(df))}\n'
                "}\n"
            ),
        )
        if DB_PATH.exists():
            archive.write(DB_PATH, "sqlite/ots_otd.sqlite3")
    return output.getvalue()

