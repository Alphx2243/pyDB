"""Write-ahead log records."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydb.storage.heap_file import RowPointer
from pydb.types import Row


class LogRecordType(StrEnum):
    """WAL record types."""

    BEGIN = "BEGIN"
    COMMIT = "COMMIT"
    ROLLBACK = "ROLLBACK"
    INSERT = "INSERT"
    DELETE = "DELETE"

@dataclass(frozen=True, slots=True)
class LogRecord:
    """One logical WAL record."""
    record_type: LogRecordType
    txid: int # transaction id
    table_name: str | None = None
    row: Row | None = None # row data
    pointer: RowPointer | None = None

class WriteAheadLog:
    """Append-only JSON-lines write-ahead log."""
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+", encoding="utf-8")
        self._file.seek(0, os.SEEK_END)

    def append(self, record: LogRecord) -> None:
        """Append and fsync one log record."""
        self._file.write(json.dumps(_record_to_dict(record), separators=(",", ":")) + "\n")
        self._file.flush()
        os.fsync(self._file.fileno())

    def read_all(self) -> list[LogRecord]:
        """Read every valid record in log order."""
        self._file.flush()
        records: list[LogRecord] = []
        if not self.path.exists():
            return records
        with self.path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                records.append(_record_from_dict(json.loads(line)))
        return records

    def close(self) -> None:
        """Close the WAL file."""
        if not self._file.closed:
            self._file.flush()
            os.fsync(self._file.fileno())
            self._file.close()

    def __enter__(self) -> "WriteAheadLog":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

def _record_to_dict(record: LogRecord) -> dict[str, Any]:
    data: dict[str, Any] = {
        "type": record.record_type.value,
        "txid": record.txid,
    }
    if record.table_name is not None:
        data["table"] = record.table_name
    if record.row is not None:
        data["row"] = list(record.row)
    if record.pointer is not None:
        data["pointer"] = [record.pointer.page_id, record.pointer.slot_id]
    return data

def _record_from_dict(data: dict[str, Any]) -> LogRecord:
    pointer = None
    if "pointer" in data:
        pointer = RowPointer(page_id=data["pointer"][0], slot_id=data["pointer"][1])
    row = None
    if "row" in data:
        row = tuple(data["row"])
    return LogRecord(
        record_type=LogRecordType(data["type"]),
        txid=data["txid"],
        table_name=data.get("table"),
        row=row,
        pointer=pointer,
    )
