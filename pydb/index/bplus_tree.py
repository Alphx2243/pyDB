"""Persistent integer-key B+ tree index."""

from __future__ import annotations
import json
import struct
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from pydb.storage.heap_file import RowPointer
from pydb.storage.page import PAGE_SIZE, Page
from pydb.storage.pager import Pager

NODE_MAGIC = b"BPTN"
NODE_HEADER_FORMAT = ">4sI"
NODE_HEADER_SIZE = struct.calcsize(NODE_HEADER_FORMAT)
NO_PAGE = 0xFFFFFFFF
MAX_KEYS = 32
MIN_KEYS = MAX_KEYS // 2

@dataclass(slots=True)
class BPlusNode:
    """One B+ tree node stored inside one database page."""
    page_id: int
    is_leaf: bool
    keys: list[int]
    values: list[list[RowPointer]]
    children: list[int]
    next_leaf: int

class BPlusTree:
    """Persistent B+ tree mapping integer keys to row pointers."""
    def __init__(self, pager: Pager, root_page_id: int) -> None:
        self.pager = pager
        self.root_page_id = root_page_id

    @classmethod
    def create(cls, pager: Pager) -> "BPlusTree":
        """Create a new tree with one empty leaf root."""
        page = pager.allocate_page()
        root = BPlusNode(page_id=page.page_id, is_leaf=True, keys=[], values=[], children=[], next_leaf=NO_PAGE,)
        _write_node(pager, root)
        return cls(pager, root.page_id)

    def search(self, key: int) -> list[RowPointer]:
        """Return all row pointers for an integer key."""
        if not isinstance(key, int):
            raise TypeError("B+ tree keys must be integers")
        leaf = self._find_leaf(key)
        index = bisect_left(leaf.keys, key)
        if index < len(leaf.keys) and leaf.keys[index] == key:
            return list(leaf.values[index])
        return []

    def insert(self, key: int, pointer: RowPointer) -> None:
        """Insert one key to row-pointer mapping."""
        if not isinstance(key, int):
            raise TypeError("B+ tree keys must be integers")
        split = self._insert_recursive(self.root_page_id, key, pointer)
        if split is None:
            return
        promoted_key, new_child_page_id = split
        new_root_page = self.pager.allocate_page()
        new_root = BPlusNode(
            page_id=new_root_page.page_id, is_leaf=False, keys=[promoted_key], values=[], children=[self.root_page_id, new_child_page_id], next_leaf=NO_PAGE,
        )
        _write_node(self.pager, new_root)
        self.root_page_id = new_root.page_id

    def delete(self, key: int, pointer: RowPointer) -> bool:
        """Remove one key to row-pointer mapping and rebalance underfull nodes."""
        if not isinstance(key, int):
            raise TypeError("B+ tree keys must be integers")

        path: list[tuple[BPlusNode, int]] = []
        leaf = self._find_leaf_with_path(key, path)
        index = bisect_left(leaf.keys, key)
        if index >= len(leaf.keys) or leaf.keys[index] != key:
            return False

        try:
            leaf.values[index].remove(pointer)
        except ValueError:
            return False

        if not leaf.values[index]:
            del leaf.values[index]
            del leaf.keys[index]

        if leaf.page_id == self.root_page_id:
            _write_node(self.pager, leaf)
            return True

        if len(leaf.keys) >= MIN_KEYS:
            _write_node(self.pager, leaf)
            self._refresh_parent_separator(path, leaf)
            return True

        self._rebalance_leaf(leaf, path)
        return True

    def _find_leaf(self, key: int) -> BPlusNode:
        return self._find_leaf_with_path(key, [])

    def _find_leaf_with_path(
        self,
        key: int,
        path: list[tuple[BPlusNode, int]],
    ) -> BPlusNode:
        node = _read_node(self.pager, self.root_page_id)
        while not node.is_leaf:
            child_index = bisect_right(node.keys, key)
            path.append((node, child_index))
            node = _read_node(self.pager, node.children[child_index])
        return node

    def _refresh_parent_separator(
        self,
        path: list[tuple[BPlusNode, int]],
        child: BPlusNode,
    ) -> None:
        if not path or not child.keys:
            return
        parent, child_index = path[-1]
        if child_index > 0:
            parent.keys[child_index - 1] = _first_key(child)
            _write_node(self.pager, parent)

    def _rebalance_leaf(self, leaf: BPlusNode, path: list[tuple[BPlusNode, int]]) -> None:
        parent, child_index = path[-1]
        left = _read_node(self.pager, parent.children[child_index - 1]) if child_index > 0 else None
        right = (
            _read_node(self.pager, parent.children[child_index + 1])
            if child_index + 1 < len(parent.children)
            else None
        )

        if left is not None and len(left.keys) > MIN_KEYS:
            leaf.keys.insert(0, left.keys.pop())
            leaf.values.insert(0, left.values.pop())
            parent.keys[child_index - 1] = leaf.keys[0]
            _write_node(self.pager, left)
            _write_node(self.pager, leaf)
            _write_node(self.pager, parent)
            return

        if right is not None and len(right.keys) > MIN_KEYS:
            leaf.keys.append(right.keys.pop(0))
            leaf.values.append(right.values.pop(0))
            parent.keys[child_index] = right.keys[0]
            _write_node(self.pager, right)
            _write_node(self.pager, leaf)
            _write_node(self.pager, parent)
            return

        if left is not None:
            left.keys.extend(leaf.keys)
            left.values.extend(leaf.values)
            left.next_leaf = leaf.next_leaf
            del parent.keys[child_index - 1]
            del parent.children[child_index]
            _write_node(self.pager, left)
        elif right is not None:
            leaf.keys.extend(right.keys)
            leaf.values.extend(right.values)
            leaf.next_leaf = right.next_leaf
            del parent.keys[child_index]
            del parent.children[child_index + 1]
            _write_node(self.pager, leaf)

        self._finish_parent_after_child_merge(parent, path[:-1])

    def _finish_parent_after_child_merge(
        self,
        parent: BPlusNode,
        path_to_parent: list[tuple[BPlusNode, int]],
    ) -> None:
        if parent.page_id == self.root_page_id:
            if not parent.is_leaf and len(parent.keys) == 0 and parent.children:
                self.root_page_id = parent.children[0]
            else:
                _write_node(self.pager, parent)
            return

        if len(parent.keys) >= MIN_KEYS:
            _write_node(self.pager, parent)
            return

        self._rebalance_internal(parent, path_to_parent)

    def _rebalance_internal(
        self,
        node: BPlusNode,
        path: list[tuple[BPlusNode, int]],
    ) -> None:
        parent, child_index = path[-1]
        left = _read_node(self.pager, parent.children[child_index - 1]) if child_index > 0 else None
        right = (
            _read_node(self.pager, parent.children[child_index + 1])
            if child_index + 1 < len(parent.children)
            else None
        )

        if left is not None and len(left.keys) > MIN_KEYS:
            node.keys.insert(0, parent.keys[child_index - 1])
            node.children.insert(0, left.children.pop())
            parent.keys[child_index - 1] = left.keys.pop()
            _write_node(self.pager, left)
            _write_node(self.pager, node)
            _write_node(self.pager, parent)
            return

        if right is not None and len(right.keys) > MIN_KEYS:
            node.keys.append(parent.keys[child_index])
            node.children.append(right.children.pop(0))
            parent.keys[child_index] = right.keys.pop(0)
            _write_node(self.pager, right)
            _write_node(self.pager, node)
            _write_node(self.pager, parent)
            return

        if left is not None:
            left.keys.append(parent.keys[child_index - 1])
            left.keys.extend(node.keys)
            left.children.extend(node.children)
            del parent.keys[child_index - 1]
            del parent.children[child_index]
            _write_node(self.pager, left)
        elif right is not None:
            node.keys.append(parent.keys[child_index])
            node.keys.extend(right.keys)
            node.children.extend(right.children)
            del parent.keys[child_index]
            del parent.children[child_index + 1]
            _write_node(self.pager, node)

        self._finish_parent_after_child_merge(parent, path[:-1])

    def _insert_recursive( self, page_id: int, key: int, pointer: RowPointer, ) -> tuple[int, int] | None:
        node = _read_node(self.pager, page_id)
        if node.is_leaf:
            return self._insert_into_leaf(node, key, pointer)
        child_index = bisect_right(node.keys, key)
        child_page_id = node.children[child_index]
        split = self._insert_recursive(child_page_id, key, pointer)
        if split is None:
            return None
        promoted_key, new_child_page_id = split
        insert_at = bisect_right(node.keys, promoted_key)
        node.keys.insert(insert_at, promoted_key)
        node.children.insert(insert_at + 1, new_child_page_id)
        if len(node.keys) <= MAX_KEYS:
            _write_node(self.pager, node)
            return None
        return self._split_internal(node)

    def _insert_into_leaf(self, leaf: BPlusNode, key: int, pointer: RowPointer,) -> tuple[int, int] | None:
        index = bisect_left(leaf.keys, key)
        if index < len(leaf.keys) and leaf.keys[index] == key:
            leaf.values[index].append(pointer)
        else:
            leaf.keys.insert(index, key)
            leaf.values.insert(index, [pointer])

        if len(leaf.keys) <= MAX_KEYS:
            _write_node(self.pager, leaf)
            return None

        return self._split_leaf(leaf)

    def _split_leaf(self, leaf: BPlusNode) -> tuple[int, int]:
        split_at = len(leaf.keys) // 2
        new_page = self.pager.allocate_page()
        new_leaf = BPlusNode(
            page_id=new_page.page_id,
            is_leaf=True,
            keys=leaf.keys[split_at:],
            values=leaf.values[split_at:],
            children=[],
            next_leaf=leaf.next_leaf,
        )

        leaf.keys = leaf.keys[:split_at]
        leaf.values = leaf.values[:split_at]
        leaf.next_leaf = new_leaf.page_id

        _write_node(self.pager, leaf)
        _write_node(self.pager, new_leaf)
        return new_leaf.keys[0], new_leaf.page_id

    def _split_internal(self, node: BPlusNode) -> tuple[int, int]:
        split_at = len(node.keys) // 2
        promoted_key = node.keys[split_at]

        new_page = self.pager.allocate_page()
        new_internal = BPlusNode(
            page_id=new_page.page_id,
            is_leaf=False,
            keys=node.keys[split_at + 1 :],
            values=[],
            children=node.children[split_at + 1 :],
            next_leaf=NO_PAGE,
        )

        node.keys = node.keys[:split_at]
        node.children = node.children[: split_at + 1]

        _write_node(self.pager, node)
        _write_node(self.pager, new_internal)
        return promoted_key, new_internal.page_id

def _read_node(pager: Pager, page_id: int) -> BPlusNode:
    page = pager.read_page(page_id)
    magic, payload_length = struct.unpack(NODE_HEADER_FORMAT, page.data[:NODE_HEADER_SIZE])
    if magic != NODE_MAGIC:
        raise ValueError(f"page {page_id} is not a B+ tree node")
    if payload_length + NODE_HEADER_SIZE > PAGE_SIZE:
        raise ValueError("B+ tree node payload is corrupted")
    payload = bytes(page.data[NODE_HEADER_SIZE : NODE_HEADER_SIZE + payload_length])
    raw = json.loads(payload.decode("utf-8"))
    return BPlusNode(
        page_id=page_id, is_leaf=raw["is_leaf"], keys=list(raw["keys"]),
        values=[
            [RowPointer(page_id=pointer[0], slot_id=pointer[1]) for pointer in pointer_list]
            for pointer_list in raw.get("values", [])
        ],
        children=list(raw.get("children", [])),
        next_leaf=raw.get("next_leaf", NO_PAGE),
    )


def _first_key(node: BPlusNode) -> int:
    if not node.keys:
        raise ValueError("cannot read first key from an empty node")
    return node.keys[0]


def _write_node(pager: Pager, node: BPlusNode) -> None:
    page = pager.read_page(node.page_id)
    raw = {
        "is_leaf": node.is_leaf,
        "keys": node.keys,
        "values": [
            [[pointer.page_id, pointer.slot_id] for pointer in pointer_list]
            for pointer_list in node.values
        ],
        "children": node.children,
        "next_leaf": node.next_leaf,
    }
    payload = json.dumps(raw, separators=(",", ":")).encode("utf-8")
    if len(payload) + NODE_HEADER_SIZE > PAGE_SIZE:
        raise ValueError("B+ tree node is too large for one page")
    page.data[:] = b"\x00" * PAGE_SIZE
    page.data[:NODE_HEADER_SIZE] = struct.pack(NODE_HEADER_FORMAT, NODE_MAGIC, len(payload))
    page.data[NODE_HEADER_SIZE : NODE_HEADER_SIZE + len(payload)] = payload
    pager.write_page(page)
