"""SQL statement executor."""

from __future__ import annotations
from dataclasses import dataclass
from pydb.catalog import Catalog
from pydb.index.bplus_tree import BPlusTree
from pydb.sql.ast import (
    BinaryOperator, CreateIndexStatement, CreateTableStatement, DeleteStatement, InsertStatement, SelectStatement,
    Statement, TransactionStatement, WhereClause,
)
from pydb.storage.heap_file import HeapFile
from pydb.storage.pager import Pager
from pydb.transaction.txn import TransactionManager
from pydb.types import ColumnType, Row, Schema, Value

@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Result returned by the executor."""
    message: str
    columns: tuple[str, ...] = ()
    rows: tuple[Row, ...] = ()

def execute(
    statement: Statement,
    catalog: Catalog,
    pager: Pager,
    txn_manager: TransactionManager | None = None,
) -> ExecutionResult:
    """Execute one parsed SQL statement."""
    if isinstance(statement, CreateTableStatement):
        return _execute_create_table(statement, catalog, pager)
    if isinstance(statement, InsertStatement):
        return _execute_insert(statement, catalog, pager, txn_manager)
    if isinstance(statement, SelectStatement):
        return _execute_select(statement, catalog, pager)
    if isinstance(statement, DeleteStatement):
        return _execute_delete(statement, catalog, pager, txn_manager)
    if isinstance(statement, CreateIndexStatement):
        return _execute_create_index(statement, catalog, pager)
    if isinstance(statement, TransactionStatement):
        return _execute_transaction(statement, txn_manager)
    raise TypeError(f"unsupported statement: {statement!r}")

def _execute_create_table( statement: CreateTableStatement, catalog: Catalog, pager: Pager, ) -> ExecutionResult:
    schema = Schema(statement.columns)
    heap = HeapFile.create(pager, schema)
    catalog.create_table(statement.table_name, schema, heap.first_page_id)
    return ExecutionResult(f"Table {statement.table_name} created.")

def _execute_insert(
    statement: InsertStatement,
    catalog: Catalog,
    pager: Pager,
    txn_manager: TransactionManager | None = None,
) -> ExecutionResult:
    table = catalog.get_table(statement.table_name)
    heap = HeapFile(pager, table.schema, table.first_page_id)

    txid = None
    auto_commit = False
    if txn_manager is not None:
        txid, auto_commit = txn_manager.transaction_for_write()

    try:
        pointer = heap.insert(statement.values)
        if txn_manager is not None and txid is not None:
            txn_manager.log_insert(txid, statement.table_name, statement.values, pointer)

        for index_name, index in table.indexes.items():
            column_index = _column_index(table.schema, index.column_name)
            key = statement.values[column_index]
            if not isinstance(key, int):
                raise TypeError("only INT columns can be indexed")
            tree = BPlusTree(pager, index.root_page_id)
            tree.insert(key, pointer)
            if tree.root_page_id != index.root_page_id:
                catalog.update_index_root(statement.table_name, index_name, tree.root_page_id)

        if txn_manager is not None and auto_commit:
            txn_manager.commit()
    except Exception:
        if txn_manager is not None and auto_commit and txn_manager.active_txid is not None:
            txn_manager.rollback()
        raise

    return ExecutionResult("1 row inserted.")

def _execute_select(statement: SelectStatement, catalog: Catalog, pager: Pager) -> ExecutionResult:
    table = catalog.get_table(statement.table_name)
    heap = HeapFile(pager, table.schema, table.first_page_id)
    indexed_rows = _try_indexed_select(statement, table, heap, pager)
    if indexed_rows is None:
        rows = tuple(row for _, row in heap.scan() if _matches_where(table.schema, row, statement.where))
    else:
        rows = indexed_rows
    columns = tuple(column.name for column in table.schema.columns)
    return ExecutionResult(f"{len(rows)} row(s) selected.", columns=columns, rows=rows)

def _execute_delete(
    statement: DeleteStatement,
    catalog: Catalog,
    pager: Pager,
    txn_manager: TransactionManager | None = None,
) -> ExecutionResult:
    table = catalog.get_table(statement.table_name)
    heap = HeapFile(pager, table.schema, table.first_page_id)
    deleted_count = 0

    txid = None
    auto_commit = False
    if txn_manager is not None:
        txid, auto_commit = txn_manager.transaction_for_write()

    try:
        for pointer, row in list(heap.scan()):
            if _matches_where(table.schema, row, statement.where):
                if txn_manager is not None and txid is not None:
                    txn_manager.log_delete(txid, statement.table_name, row, pointer)
                heap.delete(pointer)
                _remove_index_entries(statement.table_name, table, row, pointer, catalog, pager)
                deleted_count += 1

        if txn_manager is not None and auto_commit:
            txn_manager.commit()
    except Exception:
        if txn_manager is not None and auto_commit and txn_manager.active_txid is not None:
            txn_manager.rollback()
        raise

    return ExecutionResult(f"{deleted_count} row(s) deleted.")


def _remove_index_entries(
    table_name: str,
    table: object,
    row: Row,
    pointer: object,
    catalog: Catalog,
    pager: Pager,
) -> None:
    for index in table.indexes.values():
        column_index = _column_index(table.schema, index.column_name)
        key = row[column_index]
        if isinstance(key, int):
            BPlusTree(pager, index.root_page_id).delete(key, pointer)


def _execute_transaction(
    statement: TransactionStatement,
    txn_manager: TransactionManager | None,
) -> ExecutionResult:
    if txn_manager is None:
        return ExecutionResult(f"{statement.command} ignored: transactions are not configured.")

    if statement.command == "BEGIN":
        txid = txn_manager.begin()
        return ExecutionResult(f"Transaction {txid} started.")
    if statement.command == "COMMIT":
        txn_manager.commit()
        return ExecutionResult("Transaction committed.")
    if statement.command == "ROLLBACK":
        txn_manager.rollback()
        return ExecutionResult("Transaction rolled back.")

    raise ValueError(f"unsupported transaction command: {statement.command}")


def _execute_create_index(
    statement: CreateIndexStatement,
    catalog: Catalog,
    pager: Pager,
) -> ExecutionResult:
    table = catalog.get_table(statement.table_name)
    column_index = _column_index(table.schema, statement.column_name)
    column = table.schema.columns[column_index]
    if column.column_type != ColumnType.INT:
        raise TypeError("only INT columns can be indexed")

    tree = BPlusTree.create(pager)
    heap = HeapFile(pager, table.schema, table.first_page_id)
    indexed_count = 0
    for pointer, row in heap.scan():
        key = row[column_index]
        if not isinstance(key, int):
            raise TypeError("only INT columns can be indexed")
        tree.insert(key, pointer)
        indexed_count += 1

    catalog.add_index(
        table_name=statement.table_name,
        index_name=statement.index_name,
        column_name=statement.column_name,
        root_page_id=tree.root_page_id,
    )
    return ExecutionResult(f"Index {statement.index_name} created on {indexed_count} row(s).")


def _try_indexed_select(
    statement: SelectStatement,
    table: object,
    heap: HeapFile,
    pager: Pager,
) -> tuple[Row, ...] | None:
    where = statement.where
    if where is None or where.operator != BinaryOperator.EQ or not isinstance(where.value, int):
        return None

    for index in table.indexes.values():
        if index.column_name != where.column_name:
            continue

        tree = BPlusTree(pager, index.root_page_id)
        rows: list[Row] = []
        for pointer in tree.search(where.value):
            try:
                row = heap.get(pointer)
            except ValueError:
                continue
            if _matches_where(table.schema, row, where):
                rows.append(row)
        return tuple(rows)

    return None


def _matches_where(schema: Schema, row: Row, where: WhereClause | None) -> bool:
    if where is None:
        return True
    column_index = _column_index(schema, where.column_name)
    left = row[column_index]
    right = where.value
    return _compare(left, where.operator, right)


def _column_index(schema: Schema, column_name: str) -> int:
    column_names = [column.name for column in schema.columns]
    try:
        return column_names.index(column_name)
    except ValueError as exc:
        raise ValueError(f"unknown column: {column_name}") from exc

def _compare(left: Value, operator: BinaryOperator, right: Value) -> bool:
    if type(left) is not type(right):
        raise TypeError("WHERE value type does not match column type")
    if operator == BinaryOperator.EQ:
        return left == right
    if operator == BinaryOperator.NE:
        return left != right
    if operator == BinaryOperator.LT:
        return left < right
    if operator == BinaryOperator.LE:
        return left <= right
    if operator == BinaryOperator.GT:
        return left > right
    if operator == BinaryOperator.GE:
        return left >= right
    raise ValueError(f"unsupported operator: {operator}")
