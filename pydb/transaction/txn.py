"""Transaction manager."""
from __future__ import annotations

from pydb.catalog import Catalog
from pydb.index.bplus_tree import BPlusTree
from pydb.storage.heap_file import HeapFile, RowPointer
from pydb.transaction.wal import LogRecord, LogRecordType, WriteAheadLog
from pydb.types import Row

class TransactionManager:
    """Tracks one active transaction and writes WAL records."""
    def __init__(self, wal: WriteAheadLog, catalog: Catalog, pager: object) -> None:
        self.wal = wal
        self.catalog = catalog
        self.pager = pager
        self._next_txid = self._load_next_txid()
        self.active_txid: int | None = None

    def begin(self) -> int:
        """Start a transaction."""
        if self.active_txid is not None:
            raise RuntimeError("transaction already active")
        txid = self._next_txid
        self._next_txid += 1
        self.active_txid = txid
        self.wal.append(LogRecord(LogRecordType.BEGIN, txid))
        return txid

    def commit(self) -> None:
        """Commit the active transaction."""
        txid = self._require_active()
        self.wal.append(LogRecord(LogRecordType.COMMIT, txid))
        if hasattr(self.pager, "flush_all"):
            self.pager.flush_all()
        self.active_txid = None

    def rollback(self) -> None:
        """Undo the active transaction."""
        txid = self._require_active()
        records = [record for record in self.wal.read_all() if record.txid == txid]
        _undo_records(records, self.catalog, self.pager)
        self.wal.append(LogRecord(LogRecordType.ROLLBACK, txid))
        if hasattr(self.pager, "flush_all"):
            self.pager.flush_all()
        self.active_txid = None

    def transaction_for_write(self) -> tuple[int, bool]:
        """Return a txid and whether it should auto-commit after the statement."""
        if self.active_txid is not None:
            return self.active_txid, False
        return self.begin(), True

    def log_insert(self, txid: int, table_name: str, row: Row, pointer: RowPointer) -> None:
        """Log an inserted row before commit."""
        self.wal.append(LogRecord(LogRecordType.INSERT, txid, table_name=table_name, row=row, pointer=pointer))

    def log_delete(self, txid: int, table_name: str, row: Row, pointer: RowPointer) -> None:
        """Log a deleted row before commit."""
        self.wal.append(LogRecord(LogRecordType.DELETE, txid, table_name=table_name, row=row, pointer=pointer))

    def _require_active(self) -> int:
        if self.active_txid is None:
            raise RuntimeError("no active transaction")
        return self.active_txid

    def _load_next_txid(self) -> int:
        records = self.wal.read_all()
        if not records:
            return 1
        return max(record.txid for record in records) + 1

def _undo_records(records: list[LogRecord], catalog: Catalog, pager: object) -> None:
    for record in reversed(records):
        if record.record_type == LogRecordType.INSERT and record.table_name and record.pointer:
            table = catalog.get_table(record.table_name)
            heap = HeapFile(pager, table.schema, table.first_page_id)
            try:
                heap.delete(record.pointer)
            except ValueError:
                continue
            if record.row is not None:
                _remove_index_entries(record.table_name, record.row, record.pointer, catalog, pager)
        elif record.record_type == LogRecordType.DELETE and record.table_name and record.pointer:
            table = catalog.get_table(record.table_name)
            heap = HeapFile(pager, table.schema, table.first_page_id)
            try:
                heap.restore(record.pointer)
            except ValueError:
                continue
            if record.row is not None:
                _insert_index_entries(record.table_name, record.row, record.pointer, catalog, pager)


def _insert_index_entries(
    table_name: str,
    row: Row,
    pointer: RowPointer,
    catalog: Catalog,
    pager: object,
) -> None:
    table = catalog.get_table(table_name)
    for index_name, index in table.indexes.items():
        column_index = _column_index(table.schema, index.column_name)
        key = row[column_index]
        if not isinstance(key, int):
            continue
        tree = BPlusTree(pager, index.root_page_id)
        tree.insert(key, pointer)
        if tree.root_page_id != index.root_page_id:
            catalog.update_index_root(table_name, index_name, tree.root_page_id)


def _remove_index_entries(
    table_name: str,
    row: Row,
    pointer: RowPointer,
    catalog: Catalog,
    pager: object,
) -> None:
    table = catalog.get_table(table_name)
    for index in table.indexes.values():
        column_index = _column_index(table.schema, index.column_name)
        key = row[column_index]
        if isinstance(key, int):
            BPlusTree(pager, index.root_page_id).delete(key, pointer)


def _column_index(schema: object, column_name: str) -> int:
    column_names = [column.name for column in schema.columns]
    return column_names.index(column_name)
