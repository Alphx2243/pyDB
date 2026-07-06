"""LRU buffer pool for database pages."""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass

from pydb.storage.page import Page
from pydb.storage.pager import Pager

@dataclass(slots=True)
class BufferFrame:
    """A cached page plus its dirty bit."""
    page: Page
    dirty: bool = False

@dataclass(frozen=True, slots=True)
class BufferPoolStats:
    """Cache hit/miss counters."""
    hits: int
    misses: int

class BufferPool:
    """Caches pages from the pager and evicts them using LRU."""
    def __init__(self, pager: Pager, capacity: int = 128) -> None:
        if capacity <= 0:
            raise ValueError("buffer pool capacity must be positive")
        self.pager = pager
        self.capacity = capacity
        self._frames: OrderedDict[int, BufferFrame] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def page_count(self) -> int:
        """Return the number of pages in the underlying database file."""
        return self.pager.page_count()

    def fetch_page(self, page_id: int) -> Page:
        """Fetch a page from cache or disk."""
        frame = self._frames.get(page_id)
        if frame is not None:
            self._hits += 1
            self._frames.move_to_end(page_id)
            return frame.page
        self._misses += 1
        self._ensure_capacity()
        page = self.pager.read_page(page_id)
        self._frames[page_id] = BufferFrame(page=page)
        return page

    def read_page(self, page_id: int) -> Page:
        """Pager-compatible read method."""
        return self.fetch_page(page_id)

    def write_page(self, page: Page) -> None:
        """Mark a page dirty in the buffer pool."""
        frame = self._frames.get(page.page_id)
        if frame is None:
            self._ensure_capacity()
            self._frames[page.page_id] = BufferFrame(page=page, dirty=True)
        else:
            frame.page = page
            frame.dirty = True
            self._frames.move_to_end(page.page_id)

    def mark_dirty(self, page_id: int) -> None:
        """Mark a cached page as dirty."""
        try:
            frame = self._frames[page_id]
        except KeyError as exc:
            raise KeyError(f"page {page_id} is not in the buffer pool") from exc
        frame.dirty = True
        self._frames.move_to_end(page_id)

    def allocate_page(self) -> Page:
        """Allocate a new page and cache it."""
        page = self.pager.allocate_page()
        self._ensure_capacity()
        self._frames[page.page_id] = BufferFrame(page=page)
        return page

    def flush_page(self, page_id: int) -> None:
        """Flush one dirty page to disk."""
        frame = self._frames.get(page_id)
        if frame is None or not frame.dirty:
            return
        self.pager.write_page(frame.page)
        frame.dirty = False

    def flush_all(self) -> None:
        """Flush every dirty page to disk."""
        for page_id in list(self._frames):
            self.flush_page(page_id)

    def stats(self) -> BufferPoolStats:
        """Return cache statistics."""
        return BufferPoolStats(hits=self._hits, misses=self._misses)

    def close(self) -> None:
        """Flush dirty pages and close the underlying pager."""
        self.flush_all()
        self.pager.close()

    def _ensure_capacity(self) -> None:
        if len(self._frames) < self.capacity:
            return
        page_id, frame = self._frames.popitem(last=False)
        if frame.dirty:
            self.pager.write_page(frame.page)

    def __enter__(self) -> "BufferPool":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()