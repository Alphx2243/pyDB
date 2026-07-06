"""Heap-file table storage."""

from __future__ import annotations
import struct
from dataclasses import dataclass
from typing import Iterator

from pydb.storage.page import PAGE_SIZE, Page
from pydb.storage.pager import Pager
from pydb.storage.record import decode_record, encode_record
from pydb.types import Row, Schema


NO_PAGE = 0xFFFFFFFF # this is the last page in the heap
PAGE_MAGIC = b"HEAP" # This is a 4-byte marker stored at the beginning of every heap page. [This is a 4-byte marker stored at 
# the beginning of every heap page.]
HEADER_FORMAT = ">4sIHH" # > = Big endian, 4s = 4 byte string, I = unsigned int (4 bytes), H = unsigned short (2 bytes)
HEADER_SIZE = struct.calcsize(HEADER_FORMAT) # Calculate the size of the header based on the format string. This will be used to 
# determine where the header ends and the data begins in a heap page.
SLOT_FORMAT = ">HHB" # > = Big endian, B = unsigned char (1 byte)
SLOT_SIZE = struct.calcsize(SLOT_FORMAT) # Calculate the size of a slot based on the format string. This will be used to 
# determine where each slot starts and ends in a
SLOT_LIVE = 1 # This is a flag that indicates that a slot is live (i.e., it contains a valid row). 
SLOT_DELETED = 0 # This is a flag that indicates that a slot is deleted (i.e., it does not contain a valid row).


@dataclass(frozen=True, slots=True)
class RowPointer:
    """Physical location of a row in a table heap."""
    page_id: int
    slot_id: int


class HeapFile:
    """Append-oriented heap storage for rows belonging to one table."""
    def __init__(self, pager: Pager, schema: Schema, first_page_id: int) -> None:
        self.pager = pager
        self.schema = schema
        self.first_page_id = first_page_id

    @classmethod
    def create(cls, pager: Pager, schema: Schema) -> "HeapFile":
        """Allocate the first heap page for a new table."""
        page = pager.allocate_page()
        _init_heap_page(page)
        pager.write_page(page)
        return cls(pager=pager, schema=schema, first_page_id=page.page_id)

    def insert(self, row: Row) -> RowPointer:
        """Insert a row and return its row pointer."""
        encoded = encode_record(self.schema, row)
        page_id = self.first_page_id

        while True:
            page = self.pager.read_page(page_id)
            header = _read_header(page)
            slot_id = _try_insert_into_page(page, encoded)
            if slot_id is not None:
                self.pager.write_page(page)
                return RowPointer(page_id=page_id, slot_id=slot_id)

            if header.next_page_id == NO_PAGE:
                next_page = self.pager.allocate_page()
                _init_heap_page(next_page)
                self.pager.write_page(next_page)

                _write_header(page,
                    HeapPageHeader(next_page_id=next_page.page_id, slot_count=header.slot_count, free_start=header.free_start, ),
                )
                self.pager.write_page(page)
                page_id = next_page.page_id
            else:
                page_id = header.next_page_id

    def scan(self) -> Iterator[tuple[RowPointer, Row]]:
        """Yield all live rows in insertion order."""
        page_id = self.first_page_id
        while page_id != NO_PAGE:
            page = self.pager.read_page(page_id)
            header = _read_header(page)
            for slot_id in range(header.slot_count):
                offset, length, flags = _read_slot(page, slot_id)
                if flags == SLOT_LIVE:
                    data = bytes(page.data[offset : offset + length])
                    yield RowPointer(page_id, slot_id), decode_record(self.schema, data)
            page_id = header.next_page_id

    def delete(self, pointer: RowPointer) -> None:
        """Mark a row deleted without moving bytes around."""
        page = self.pager.read_page(pointer.page_id)
        header = _read_header(page)
        if pointer.slot_id < 0 or pointer.slot_id >= header.slot_count:
            raise ValueError("slot_id is out of range")
        offset, length, flags = _read_slot(page, pointer.slot_id)
        if flags != SLOT_LIVE:
            return
        _write_slot(page, pointer.slot_id, offset, length, SLOT_DELETED)
        self.pager.write_page(page)

    def restore(self, pointer: RowPointer) -> None:
        """Mark a tombstoned row live again."""
        page = self.pager.read_page(pointer.page_id)
        header = _read_header(page)
        if pointer.slot_id < 0 or pointer.slot_id >= header.slot_count:
            raise ValueError("slot_id is out of range")

        offset, length, flags = _read_slot(page, pointer.slot_id)
        if flags == SLOT_LIVE:
            return

        _write_slot(page, pointer.slot_id, offset, length, SLOT_LIVE)
        self.pager.write_page(page)

    def get(self, pointer: RowPointer) -> Row:
        """Read one live row by pointer."""
        page = self.pager.read_page(pointer.page_id)
        header = _read_header(page)
        if pointer.slot_id < 0 or pointer.slot_id >= header.slot_count:
            raise ValueError("slot_id is out of range")
        offset, length, flags = _read_slot(page, pointer.slot_id)
        if flags != SLOT_LIVE:
            raise ValueError("row has been deleted")
        return decode_record(self.schema, bytes(page.data[offset : offset + length]))


@dataclass(frozen=True, slots=True)
class HeapPageHeader:
    next_page_id: int
    slot_count: int
    free_start: int


def _init_heap_page(page: Page) -> None:
    page.data[:] = b"\x00" * PAGE_SIZE
    _write_header(page, HeapPageHeader(next_page_id=NO_PAGE, slot_count=0, free_start=PAGE_SIZE))


def _read_header(page: Page) -> HeapPageHeader:
    magic, next_page_id, slot_count, free_start = struct.unpack(
        HEADER_FORMAT, page.data[:HEADER_SIZE]
    )
    if magic != PAGE_MAGIC:
        raise ValueError(f"page {page.page_id} is not a heap page")
    return HeapPageHeader(
        next_page_id=next_page_id,
        slot_count=slot_count,
        free_start=free_start,
    )


def _write_header(page: Page, header: HeapPageHeader) -> None:
    page.data[:HEADER_SIZE] = struct.pack(
        HEADER_FORMAT, PAGE_MAGIC, header.next_page_id, header.slot_count, header.free_start,
    )


def _try_insert_into_page(page: Page, record: bytes) -> int | None:
    header = _read_header(page)
    next_slot_end = HEADER_SIZE + ((header.slot_count + 1) * SLOT_SIZE)
    record_start = header.free_start - len(record)
    if record_start < next_slot_end:
        return None
    slot_id = header.slot_count
    page.data[record_start : record_start + len(record)] = record
    _write_slot(page, slot_id, record_start, len(record), SLOT_LIVE)
    _write_header(
        page,
        HeapPageHeader(
            next_page_id=header.next_page_id, slot_count=header.slot_count + 1, free_start=record_start,
        ),
    )
    return slot_id


def _read_slot(page: Page, slot_id: int) -> tuple[int, int, int]:
    start = HEADER_SIZE + (slot_id * SLOT_SIZE)
    return struct.unpack(SLOT_FORMAT, page.data[start : start + SLOT_SIZE])


def _write_slot(page: Page, slot_id: int, offset: int, length: int, flags: int) -> None:
    start = HEADER_SIZE + (slot_id * SLOT_SIZE)
    page.data[start : start + SLOT_SIZE] = struct.pack(SLOT_FORMAT, offset, length, flags)
