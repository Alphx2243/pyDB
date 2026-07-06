"""Schema-aware row serialization."""

from __future__ import annotations
import struct
from pydb.types import ColumnType, Row, Schema, Value


INT_SIZE = 8
TEXT_LENGTH_SIZE = 4


def encode_record(schema: Schema, row: Row) -> bytes:
    """Encode a row into bytes using its schema."""
    schema.validate_row(row)
    chunks: list[bytes] = []
    for column, value in zip(schema.columns, row, strict=True):
        if column.column_type == ColumnType.INT:
            chunks.append(_encode_int(value))
        elif column.column_type == ColumnType.TEXT:
            chunks.append(_encode_text(value))
        else:
            raise ValueError(f"unsupported column type: {column.column_type}")

    return b"".join(chunks)


def decode_record(schema: Schema, data: bytes) -> Row:
    """Decode bytes into a row using its schema."""
    values: list[Value] = []
    offset = 0
    for column in schema.columns:
        if column.column_type == ColumnType.INT:
            value, offset = _decode_int(data, offset)
        elif column.column_type == ColumnType.TEXT:
            value, offset = _decode_text(data, offset)
        else:
            raise ValueError(f"unsupported column type: {column.column_type}")
        values.append(value)

    if offset != len(data):
        raise ValueError("record contains trailing bytes")

    return tuple(values)


def _encode_int(value: Value) -> bytes:
    if not isinstance(value, int):
        raise TypeError("INT value must be an int")
    return struct.pack(">q", value)


def _decode_int(data: bytes, offset: int) -> tuple[int, int]:
    end = offset + INT_SIZE
    if end > len(data):
        raise ValueError("record ended while reading INT")
    return struct.unpack(">q", data[offset:end])[0], end


def _encode_text(value: Value) -> bytes:
    if not isinstance(value, str):
        raise TypeError("TEXT value must be a str")
    encoded = value.encode("utf-8")
    return struct.pack(">I", len(encoded)) + encoded


def _decode_text(data: bytes, offset: int) -> tuple[str, int]:
    length_end = offset + TEXT_LENGTH_SIZE
    if length_end > len(data):
        raise ValueError("record ended while reading TEXT length")
    length = struct.unpack(">I", data[offset:length_end])[0]
    value_end = length_end + length
    if value_end > len(data):
        raise ValueError("record ended while reading TEXT value")
    return data[length_end:value_end].decode("utf-8"), value_end
