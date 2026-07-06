"""SQL abstract syntax tree definitions. (convert to statements) """

from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from pydb.types import Column, Value

class BinaryOperator(StrEnum):
    """WHERE operators supported by PyDB."""
    EQ = "="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="

@dataclass(frozen=True, slots=True)
class WhereClause:
    """A simple column/value predicate."""
    column_name: str
    operator: BinaryOperator
    value: Value

@dataclass(frozen=True, slots=True)
class CreateTableStatement:
    table_name: str
    columns: tuple[Column, ...]

@dataclass(frozen=True, slots=True)
class InsertStatement:
    table_name: str
    values: tuple[Value, ...]

@dataclass(frozen=True, slots=True)
class SelectStatement:
    table_name: str
    where: WhereClause | None = None

@dataclass(frozen=True, slots=True)
class DeleteStatement:
    table_name: str
    where: WhereClause

@dataclass(frozen=True, slots=True)
class CreateIndexStatement:
    index_name: str
    table_name: str
    column_name: str

@dataclass(frozen=True, slots=True)
class TransactionStatement:
    command: str

Statement = (
    CreateTableStatement | CreateIndexStatement | TransactionStatement
    | InsertStatement | SelectStatement | DeleteStatement
)
