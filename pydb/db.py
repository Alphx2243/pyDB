"""Top-level database facade."""

from __future__ import annotations
from pathlib import Path

from pydb.buffer.buffer_pool import BufferPool
from pydb.catalog import Catalog
from pydb.sql.executor import ExecutionResult, execute
from pydb.sql.parser import parse
from pydb.storage.pager import Pager
from pydb.transaction.recovery import recover
from pydb.transaction.txn import TransactionManager
from pydb.transaction.wal import WriteAheadLog

class Database:
    """Owns the pager, catalog, and SQL execution entry point."""
    def __init__(self, path: str | Path, buffer_pool_capacity: int = 128) -> None:
        self.path = Path(path)
        self.pager = Pager(path)
        self.buffer_pool = BufferPool(self.pager, capacity=buffer_pool_capacity)
        self.catalog = Catalog(self.buffer_pool)
        self.wal = WriteAheadLog(f"{self.path}-wal")
        recover(self.wal, self.catalog, self.buffer_pool)
        self.txn_manager = TransactionManager(self.wal, self.catalog, self.buffer_pool)

    def execute(self, sql: str) -> ExecutionResult:
        """Parse and execute one SQL statement."""
        statement = parse(sql)
        return execute(statement, self.catalog, self.buffer_pool, self.txn_manager)

    def list_tables(self) -> list[str]:
        """Return user table names."""
        return self.catalog.list_tables()

    def schema_for(self, table_name: str) -> str:
        """Return a compact CREATE TABLE-style schema string."""
        table = self.catalog.get_table(table_name)
        columns = ", ".join(f"{column.name} {column.column_type.value}" for column in table.schema.columns)
        return f"CREATE TABLE {table.name} ({columns});"

    def close(self) -> None:
        """Close the database."""
        self.buffer_pool.close()
        self.wal.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
