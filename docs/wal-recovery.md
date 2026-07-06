# WAL And Recovery

PyDB implements a simplified logical write-ahead log.

## WAL Rule

Before a transaction is trusted, PyDB writes log records to a `.db-wal` file. The WAL uses JSON-lines records and calls `fsync` so the operating system is asked to persist the log.

## Log Records

Supported records:

- `BEGIN`
- `INSERT`
- `DELETE`
- `COMMIT`
- `ROLLBACK`

`INSERT` and `DELETE` records store the table name, row data, and row pointer.

## Transactions

`BEGIN` starts a transaction.

`COMMIT` writes a commit record and flushes dirty pages.

`ROLLBACK` walks the transaction's records backward:

- undo an insert by tombstoning the inserted row
- undo a delete by restoring the tombstoned row

Indexes are updated during undo so indexed lookups remain consistent.

## Recovery

Recovery runs when the database opens.

- committed changes are replayed conservatively
- uncommitted changes are undone
- dirty pages are flushed after recovery

