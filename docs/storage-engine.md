# Storage Engine

PyDB stores data in fixed-size pages.

```text
page size = 4096 bytes
page id 0 = catalog metadata
page id 1+ = heap pages, index pages, and other structures
```

## Pager

The pager translates page IDs into file offsets:

```text
offset = page_id * 4096
```

It can allocate, read, and write pages.

## Records

Records are encoded from Python values into bytes.

```text
INT  -> 8 bytes signed integer
TEXT -> 4-byte length + UTF-8 bytes
```

Because `TEXT` is variable length, rows are variable length.

## Heap Pages

Heap pages use a slotted-page layout:

```text
header
slot array grows forward
free space
record bytes grow backward
```

Each slot stores:

```text
offset, length, live/deleted flag
```

This lets PyDB find a row even when rows have different byte lengths.

## Deletes

Deletes mark a slot as deleted. The row bytes remain in the page.

This is simple and stable because existing row pointers do not move. The tradeoff is that deleted space is not reused yet.

## Catalog

The catalog is stored in page 0 as encoded metadata. It records table schemas and index root pages. The current catalog is intentionally simple and must fit in one page.
