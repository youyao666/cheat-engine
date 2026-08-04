from __future__ import annotations

import json
import sys
from typing import Any, TextIO


def output_json(data: Any, file: TextIO | None = None) -> None:
    target = file or sys.stdout
    json.dump(data, target, indent=2, ensure_ascii=False, default=str)
    target.write("\n")


def output_rows(rows: list[dict[str, Any]], columns: list[str], file: TextIO | None = None) -> None:
    target = file or sys.stdout
    if not rows:
        target.write("(no data)\n")
        return

    widths = {column: len(column) for column in columns}
    for row in rows:
        for column in columns:
            widths[column] = max(widths[column], len(str(row.get(column, ""))))

    target.write("  ".join(column.ljust(widths[column]) for column in columns) + "\n")
    target.write("  ".join("-" * widths[column] for column in columns) + "\n")
    for row in rows:
        target.write(
            "  ".join(str(row.get(column, "")).ljust(widths[column]) for column in columns)
            + "\n"
        )
