from pathlib import Path


def detect_format_from_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    mapping = {
        ".csv": "csv",
        ".xlsx": "xlsx",
        ".xls": "xlsx",
        ".pdf": "pdf",
        ".txt": "txt",
    }
    return mapping.get(suffix, "unknown")
