# Architecture

PyDB is split into small layers so each part has a clear job.

```text
CLI -> Parser -> Executor -> Storage/Index/Transaction -> Buffer Pool -> Pager -> Disk
```

## CLI

The CLI accepts commands from the user. Dot commands like `.tables` and `.schema users` are handled directly. SQL statements are passed to the parser after they end with `;`.

## Lexer And Parser

The lexer turns raw SQL text into tokens. The parser turns tokens into typed statement objects such as `CreateTableStatement`, `InsertStatement`, or `SelectStatement`.

This keeps execution code away from string parsing.

## Executor

The executor connects parsed SQL to database internals.

- `CREATE TABLE` creates a catalog entry and heap storage.
- `INSERT` writes to the heap and updates indexes.
- `SELECT` scans or uses an index for equality predicates.
- `DELETE` tombstones heap rows and removes index entries.
- Transaction commands call the transaction manager.

## Catalog

The catalog stores table metadata:

- table name
- columns
- column types
- first heap page
- index metadata

It is stored in page 0 of the database file.

## Storage

The storage layer stores rows in heap pages. Rows are serialized into bytes using the table schema. Each row is addressed by a `RowPointer(page_id, slot_id)`.

## Indexes

Indexes are persistent B+ trees. Leaf nodes map integer keys to row pointers. Internal nodes route searches to child pages.

## Buffer Pool

The buffer pool caches pages in memory and uses LRU eviction. Dirty pages are flushed before eviction and when the database closes.

## Transactions And WAL

The transaction manager logs row inserts and deletes before commit. Rollback walks log records backward and undoes row changes. Recovery runs at startup.
