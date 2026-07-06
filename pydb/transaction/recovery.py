"""WAL recovery."""
from __future__ import annotations

from pydb.catalog import Catalog
from pydb.storage.heap_file import HeapFile
from pydb.transaction.txn import _undo_records
from pydb.transaction.wal import LogRecord, LogRecordType, WriteAheadLog

def recover(wal: WriteAheadLog, catalog: Catalog, pager: object) -> None:
    """Recover from WAL records.
    committed row deletes are replayed, committed row inserts are checked,
    and uncommitted row changes are undone.
    """
    records = wal.read_all()
    if not records:
        return
    committed = {record.txid for record in records if record.record_type == LogRecordType.COMMIT}
    rolled_back = {record.txid for record in records if record.record_type == LogRecordType.ROLLBACK}
    begun = {record.txid for record in records if record.record_type == LogRecordType.BEGIN}
    uncommitted = begun - committed - rolled_back
    for txid in sorted(committed):
        _redo_records([record for record in records if record.txid == txid], catalog, pager)
    for txid in sorted(uncommitted):
        _undo_records([record for record in records if record.txid == txid], catalog, pager)
    if hasattr(pager, "flush_all"):
        pager.flush_all()

def _redo_records(records: list[LogRecord], catalog: Catalog, pager: object) -> None:
    for record in records:
        if record.record_type == LogRecordType.DELETE and record.table_name and record.pointer:
            table = catalog.get_table(record.table_name)
            heap = HeapFile(pager, table.schema, table.first_page_id)
            try:
                heap.delete(record.pointer)
            except ValueError:
                continue
        elif record.record_type == LogRecordType.INSERT and record.table_name and record.pointer and record.row:
            table = catalog.get_table(record.table_name)
            heap = HeapFile(pager, table.schema, table.first_page_id)
            try:
                heap.get(record.pointer)
            except ValueError:
                heap.insert(record.row)
