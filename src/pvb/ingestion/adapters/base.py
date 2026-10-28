"""Strict, lossless CSV record reading with physical line diagnostics."""

import csv
from collections.abc import Iterator
from pathlib import Path


class IngestionError(ValueError):
    """An actionable input or artifact validation error."""


def read_records(path: Path, columns: tuple[str, ...]) -> Iterator[tuple[int, dict[str, str]]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            header = next(reader, None)
            if header is None or len(header) != len(columns) or set(header) != set(columns):
                raise IngestionError(
                    f"{path}: line 1: expected CSV columns {columns}; got {header}"
                )
            previous_line = reader.line_num
            for values in reader:
                location = previous_line + 1
                previous_line = reader.line_num
                if len(values) != len(header):
                    raise IngestionError(
                        f"{path}: line {location}: malformed CSV row width; "
                        f"expected {len(header)}, got {len(values)}"
                    )
                yield location, dict(zip(header, values))
    except (OSError, UnicodeError, csv.Error) as exc:
        line = reader.line_num if "reader" in locals() else 0
        raise IngestionError(f"{path}: line {line}: {exc}") from exc


def required_text(record: dict[str, str], fields: tuple[str, ...]) -> None:
    for field in fields:
        if not record[field].strip():
            raise ValueError(f"required field {field!r} must not be empty")
