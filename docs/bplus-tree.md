# B+ Tree Index

PyDB uses a persistent B+ tree for integer equality lookups.

## Why B+ Trees

A table scan is linear:

```text
check every row
```

A B+ tree narrows the search through sorted keys:

```text
root -> internal node -> leaf -> row pointer
```

This is why indexed equality lookups stay fast as tables grow.

## Node Types

PyDB has two node types:

- leaf nodes store `key -> row pointers`
- internal nodes store routing keys and child page IDs

Leaf values can contain multiple row pointers for duplicate keys.

## Persistence

Each B+ tree node is stored in a normal database page. The catalog stores the root page ID for each index.

If the root splits, the catalog root page is updated.

## Insert

Insert finds the correct leaf, inserts the key and pointer, and splits the node if it has too many keys. Splits may propagate upward and create a new root.

## Delete

Delete removes one row pointer for a key. If no row pointers remain for that key, the key is removed from the leaf.

PyDB does not rebalance underfull nodes yet. Searches remain correct, but space usage can become less optimal after many deletes.

## Executor Integration

`CREATE INDEX idx_users_id ON users(id);` builds an index over existing rows.

Future inserts update indexes automatically. Deletes remove index entries automatically.

The executor uses an index automatically for:

```sql
SELECT * FROM users WHERE indexed_int_column = value;
```
