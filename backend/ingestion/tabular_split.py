import re
from typing import Any

NARRATIVE_HINTS = (
    "description",
    "summary",
    "comment",
    "notes",
    "investigation",
    "event",
    "narrative",
    "details",
    "remarks",
)
ID_HINTS = ("id", "complaint", "case", "reference", "number")


def classify_columns(columns: list[str], sample_rows: list[dict[str, Any]]) -> tuple[list[str], list[str], str | None]:
    narrative_cols: list[str] = []
    categorical_cols: list[str] = []
    row_id_col: str | None = None

    for col in columns:
        lower = col.lower()
        if any(hint in lower for hint in ID_HINTS):
            row_id_col = col
            categorical_cols.append(col)
            continue

        values = [str(row.get(col, "")).strip() for row in sample_rows if row.get(col) is not None]
        if not values:
            categorical_cols.append(col)
            continue

        avg_len = sum(len(v) for v in values) / len(values)
        unique_ratio = len(set(values)) / len(values)
        hint_match = any(h in lower for h in NARRATIVE_HINTS)

        if hint_match or (avg_len > 40 and unique_ratio > 0.3):
            narrative_cols.append(col)
        else:
            categorical_cols.append(col)

    return narrative_cols, categorical_cols, row_id_col


def build_row_narrative(row: dict[str, Any], narrative_cols: list[str]) -> str:
    parts = []
    for col in narrative_cols:
        value = row.get(col)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            parts.append(f"{col}: {text}")
    return "\n".join(parts)


def build_categorical_payload(row: dict[str, Any], categorical_cols: list[str]) -> dict[str, str]:
    payload: dict[str, str] = {}
    for col in categorical_cols:
        value = row.get(col)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        key = re.sub(r"[^a-z0-9_]+", "_", col.lower()).strip("_")
        if key:
            payload[key] = text[:500]
    return payload


def row_source_ref(row: dict[str, Any], row_id_col: str | None, row_index: int) -> str:
    if row_id_col:
        value = row.get(row_id_col)
        if value is not None and str(value).strip():
            return f"row:{str(value).strip()}"
    return f"row:{row_index}"
