from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO
from pydb.db import Database

PROMPT = "pydb> "
CONTINUATION_PROMPT = "...> "
HELP_TEXT = """Supported commands:
  .help          Show this help message
  .exit          Exit the shell
  .tables        List tables
  .schema NAME   Show CREATE TABLE statement for a table
SQL statements must end with a semicolon.
"""

def handle_meta_command(command: str, database: Database, output: TextIO) -> bool:
    """Handle dot-prefixed shell commands. => Returns True when the shell should continue running and 
    False when it should exit.
    """
    if command == ".exit":
        return False
    if command == ".help":
        output.write(HELP_TEXT)
        return True
    if command == ".tables":
        tables = database.list_tables()
        output.write("\n".join(tables) + ("\n" if tables else ""))
        return True
    if command.startswith(".schema"):
        parts = command.split()
        if len(parts) != 2:
            output.write("Usage: .schema <table>\n")
            return True
        try:
            output.write(database.schema_for(parts[1]) + "\n")
        except Exception as exc:
            output.write(f"Error: {exc}\n")
        return True

    output.write(f"Unrecognized command: {command}\n")
    return True

def run_shell(input_stream: TextIO = sys.stdin, output: TextIO = sys.stdout, database_path: str | Path = "pydb.db", ) -> None:
    """Run the interactive PyDB shell."""
    with Database(database_path) as database:
        pending_sql: list[str] = []
        while True:
            output.write(CONTINUATION_PROMPT if pending_sql else PROMPT)
            output.flush()
            line = input_stream.readline()
            if line == "":
                output.write("\n")
                break
            command = line.strip()
            if not command:
                continue
            if not pending_sql and command.startswith("."):
                should_continue = handle_meta_command(command, database, output)
                if not should_continue:
                    break
                continue
            pending_sql.append(command)
            if not command.endswith(";"):
                continue
            sql = " ".join(pending_sql)
            pending_sql.clear()
            try:
                result = database.execute(sql)
                _write_result(result, output)
            except Exception as exc:
                output.write(f"Error: {exc}\n")

def _write_result(result: object, output: TextIO) -> None:
    from pydb.sql.executor import ExecutionResult

    if not isinstance(result, ExecutionResult):
        output.write(f"{result}\n")
        return

    if result.columns:
        output.write(" | ".join(result.columns) + "\n")
        output.write("-+-".join("-" * len(column) for column in result.columns) + "\n")
        for row in result.rows:
            output.write(" | ".join(str(value) for value in row) + "\n")

    output.write(result.message + "\n")


def main() -> None:
    database_path = sys.argv[1] if len(sys.argv) > 1 else "pydb.db"
    run_shell(database_path=database_path)

if __name__ == "__main__":
    main()