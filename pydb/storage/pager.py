"""Disk pager for fixed-size database pages."""

from __future__ import annotations

from pathlib import Path
from pydb.storage.page import PAGE_SIZE, Page


class Pager:
    """Reads and writes fixed-size pages in a database file."""

    def __init__(self, path: str | Path) -> None:
        if not isinstance(path, (str, Path)):
            raise TypeError("path must be a string or Path object")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        mode = "r+b" if self.path.exists() else "w+b"
        self._file = self.path.open(mode)

    def page_count(self) -> int:
        """Return how many pages currently exist in the file."""
        self._file.seek(0, 2)
        size = self._file.tell()
        return (size + PAGE_SIZE - 1) // PAGE_SIZE

    def allocate_page(self) -> Page:
        """Append and return a new zero-filled page."""
        page = Page.empty(self.page_count())
        self.write_page(page)
        return page

    def read_page(self, page_id: int) -> Page:
        """Read a page by ID.

        Reading exactly one page past the current end returns a new empty page.
        Reading further than that is probably a caller bug, so it raises.
        """
        page_count = self.page_count()
        if page_id < 0 or page_id > page_count:
            raise ValueError("page_id not within valid range")
        if page_id == page_count:
            return Page.empty(page_id)
        self._file.seek(page_id * PAGE_SIZE)
        data = self._file.read(PAGE_SIZE)
        return Page.from_bytes(page_id, data)

    def write_page(self, page: Page) -> None:
        """Write a page to its fixed offset in the file."""
        self._file.seek(page.page_id * PAGE_SIZE)
        self._file.write(page.to_bytes())
        self._file.flush()

    def sync(self) -> None:
        """Force buffered writes to disk."""
        self._file.flush()
        self._file.seek(0)

    def close(self) -> None:
        """Close the database file."""
        if not self._file.closed:
            self._file.flush()
            self._file.close()

    def __enter__(self) -> "Pager":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
