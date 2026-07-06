from __future__ import annotations
from dataclasses import dataclass

PAGE_SIZE = 4096 # 4kb

@dataclass(slots=True)
class Page:
    page_id: int
    data: bytearray

    def __post_init__(self) -> None: 
        if self.page_id < 0:
            raise ValueError("page_id must be non-negative")
        if len(self.data) != PAGE_SIZE:
            raise ValueError(f"page data must be exactly {PAGE_SIZE} bytes")

    @classmethod
    def empty(cls, page_id: int) -> "Page": # create a empty page with the given page_id, filled with zero bytes.
        return cls(page_id = page_id, data = bytearray(PAGE_SIZE))

    @classmethod
    def from_bytes(cls, page_id: int, data: bytes) -> "Page": # Create a page from raw bytes read from disk.
        if len(data) > PAGE_SIZE:
            raise ValueError(f"page data cannot exceed {PAGE_SIZE} bytes")
        return cls(page_id = page_id, data = bytearray(data.ljust(PAGE_SIZE, b"\x00")))

    def to_bytes(self) -> bytes: # Return the page as bytes suitable for writing to disk.
        return bytes(self.data)
