"""Persistent database catalog."""

from __future__ import annotations
import json
import struct
from dataclasses import dataclass, field
from pydb.storage.page import PAGE_SIZE
from pydb.storage.pager import Pager
from pydb.types import Column, ColumnType, Schema

CATALOG_PAGE_ID = 0
CATALOG_LENGTH_SIZE = 4

@dataclass(frozen=True, slots=True)
class IndexMetadata:
    """Metadata for an index belonging to a table."""
    name: str
    column_name: str
    root_page_id: int


@dataclass(frozen=True, slots=True)
class TableMetadata:
    """Persistent metadata needed to open a table heap."""
    name: str
    schema: Schema
    first_page_id: int
    indexes: dict[str, IndexMetadata] = field(default_factory=dict)

class Catalog:
    """Stores table definitions in page 0 of the database file."""
    def __init__(self, pager: Pager) -> None:
        self.pager = pager
        if self.pager.page_count() == 0:
            self.pager.allocate_page()
            self._tables: dict[str, TableMetadata] = {}
            self.save()
        else:
            self._tables = self._load()

    def list_tables(self) -> list[str]:
        """Return table names in sorted order."""
        return sorted(self._tables)

    def get_table(self, name: str) -> TableMetadata:
        """Return metadata for a table."""
        try:
            return self._tables[name]
        except KeyError as exc:
            raise KeyError(f"table does not exist: {name}") from exc

    def create_table(self, name: str, schema: Schema, first_page_id: int) -> TableMetadata:
        """Create and persist a new table metadata entry."""
        if not name:
            raise ValueError("table name cannot be empty")
        if name in self._tables:
            raise ValueError(f"table already exists: {name}")
        if first_page_id <= CATALOG_PAGE_ID:
            raise ValueError("table first_page_id must point after the catalog page")
        table = TableMetadata(name=name, schema=schema, first_page_id=first_page_id)
        self._tables[name] = table
        self.save()
        return table

    def add_index( self, table_name: str, index_name: str, column_name: str, root_page_id: int,) -> None:
        """Create or replace index metadata for a table."""
        table = self.get_table(table_name)
        if index_name in table.indexes:
            raise ValueError(f"index already exists: {index_name}")
        if column_name not in {column.name for column in table.schema.columns}:
            raise ValueError(f"unknown column: {column_name}")

        table.indexes[index_name] = IndexMetadata(
            name=index_name,
            column_name=column_name,
            root_page_id=root_page_id,
        )
        self.save()

    def update_index_root(self, table_name: str, index_name: str, root_page_id: int) -> None:
        """Persist a new root page after a B+ tree root split."""
        table = self.get_table(table_name)
        try:
            index = table.indexes[index_name]
        except KeyError as exc:
            raise KeyError(f"index does not exist: {index_name}") from exc

        table.indexes[index_name] = IndexMetadata(
            name=index.name,
            column_name=index.column_name,
            root_page_id=root_page_id,
        )
        self.save()

    def save(self) -> None:
        """Write the catalog to page 0."""
        payload = json.dumps(self._to_dict(), separators=(",", ":"), sort_keys=True).encode("utf-8")
        if len(payload) + CATALOG_LENGTH_SIZE > PAGE_SIZE:
            raise ValueError("catalog is too large for the metadata page")

        page = self.pager.read_page(CATALOG_PAGE_ID)
        page.data[:] = b"\x00" * PAGE_SIZE
        page.data[:CATALOG_LENGTH_SIZE] = struct.pack(">I", len(payload))
        page.data[CATALOG_LENGTH_SIZE : CATALOG_LENGTH_SIZE + len(payload)] = payload
        self.pager.write_page(page)

    def _load(self) -> dict[str, TableMetadata]:
        """Reads catalog from disk and returns a dictionary of table metadata."""
        page = self.pager.read_page(CATALOG_PAGE_ID)
        payload_length = struct.unpack(">I", page.data[:CATALOG_LENGTH_SIZE])[0]
        if payload_length == 0:
            return {}
        if payload_length + CATALOG_LENGTH_SIZE > PAGE_SIZE:
            raise ValueError("catalog page is corrupted")

        payload = bytes(page.data[CATALOG_LENGTH_SIZE : CATALOG_LENGTH_SIZE + payload_length])
        raw = json.loads(payload.decode("utf-8"))
        tables: dict[str, TableMetadata] = {}
        for table_name, table_data in raw.get("tables", {}).items():
            schema = Schema(
                tuple(
                    Column(column["name"], ColumnType(column["type"]))
                    for column in table_data["columns"]
                )
            )
            indexes = {
                index_name: IndexMetadata(
                    name=index_name,
                    column_name=index_data["column_name"],
                    root_page_id=index_data["root_page_id"],
                )
                for index_name, index_data in table_data.get("indexes", {}).items()
            }
            tables[table_name] = TableMetadata(
                name=table_name,
                schema=schema,
                first_page_id=table_data["first_page_id"],
                indexes=indexes,
            )
        return tables

    def _to_dict(self) -> dict[str, object]:
        return {
            "tables": {
                table.name: {
                    "columns": [
                        {"name": column.name, "type": column.column_type.value}
                        for column in table.schema.columns
                    ],
                    "first_page_id": table.first_page_id,
                    "indexes": {
                        index.name: {
                            "column_name": index.column_name,
                            "root_page_id": index.root_page_id,
                        }
                        for index in table.indexes.values()
                    },
                }
                for table in self._tables.values()
            }
        }
