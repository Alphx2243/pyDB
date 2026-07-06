"""Shared PyDB type definitions."""

from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

class ColumnType(StrEnum):
    """Column types supported by PyDB."""
    INT = "INT"
    TEXT = "TEXT"

Value: TypeAlias = int | str
Row: TypeAlias = tuple[Value, ...]

@dataclass(frozen=True, slots=True)
class Column:
    """A named column in a table schema."""
    name: str
    column_type: ColumnType
    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("column name cannot be empty")

@dataclass(frozen=True, slots=True)
class Schema:
    """Ordered column definitions for a table."""
    columns: tuple[Column, ...]
    def __post_init__(self) -> None:
        if not self.columns:
            raise ValueError("schema must contain at least one column")
        names = [column.name for column in self.columns]
        if len(names) != len(set(names)):
            raise ValueError("schema cannot contain duplicate column names")

    def validate_row(self, row: Row) -> None:
        """Validate that a row matches this schema."""
        if len(row) != len(self.columns):
            raise ValueError(f"expected {len(self.columns)} values, got {len(row)}")
        for column, value in zip(self.columns, row, strict=True):
            if column.column_type == ColumnType.INT and not isinstance(value, int):
                raise TypeError(f"column {column.name} expects INT")
            if column.column_type == ColumnType.TEXT and not isinstance(value, str):
                raise TypeError(f"column {column.name} expects TEXT")