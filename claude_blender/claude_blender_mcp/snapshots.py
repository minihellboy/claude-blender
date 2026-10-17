# SPDX-License-Identifier: MIT
"""
Scene snapshots and diffs.

The addon's `scene_state` RPC returns a flat, rounded fingerprint of the
scene. Snapshots are those fingerprints held in this process under an opaque
id - the stateless-MCP pattern of "mint a handle, let the model pass it
back" - and diffs compare two of them field by field.
"""

import itertools
import time
from collections import OrderedDict
from typing import Any, Optional

_MAX_SNAPSHOTS = 32
_MAX_LISTED = 40  # per section of the human-readable summary


class SnapshotStore:
    """Bounded in-memory LRU of scene fingerprints."""

    def __init__(self, capacity: int = _MAX_SNAPSHOTS):
        self.capacity = capacity
        self._items: "OrderedDict[str, dict]" = OrderedDict()
        self._ids = itertools.count(1)

    def add(self, state: dict, label: str = "") -> str:
        snapshot_id = f"snap-{next(self._ids)}"
        self._items[snapshot_id] = {"state": state, "label": label, "taken_at": time.time()}
        while len(self._items) > self.capacity:
            self._items.popitem(last=False)
        return snapshot_id

    def get(self, snapshot_id: str) -> Optional[dict]:
        item = self._items.get(snapshot_id)
        if item is not None:
            self._items.move_to_end(snapshot_id)
        return item

    def ids(self) -> list[str]:
        return list(self._items)


def diff_states(before: dict, after: dict) -> dict:
    """Field-level diff of two scene_state payloads.

    Returns:
        {'added': [...], 'removed': [...],
         'changed': {object: {field: [old, new]}},
         'scene': {field: [old, new]}}
    """
    b_objs = before.get("objects", {})
    a_objs = after.get("objects", {})

    changed: dict[str, dict[str, list]] = {}
    for name in sorted(b_objs.keys() & a_objs.keys()):
        fields = _diff_fields(b_objs[name], a_objs[name])
        if fields:
            changed[name] = fields

    return {
        "added": sorted(a_objs.keys() - b_objs.keys()),
        "removed": sorted(b_objs.keys() - a_objs.keys()),
        "changed": changed,
        "scene": _diff_fields(before.get("scene", {}), after.get("scene", {})),
    }


def _diff_fields(old: dict, new: dict) -> dict[str, list]:
    return {
        key: [old.get(key), new.get(key)]
        for key in sorted(old.keys() | new.keys())
        if old.get(key) != new.get(key)
    }


def is_empty(diff: dict) -> bool:
    return not (diff["added"] or diff["removed"] or diff["changed"] or diff["scene"])


def summarize(diff: dict, after: Optional[dict] = None) -> str:
    """Compact human/LLM-readable rendering of a diff."""
    if is_empty(diff):
        return "No changes."

    lines = []
    a_objs = (after or {}).get("objects", {})
    if diff["added"]:
        shown = [
            f"{n} ({a_objs[n]['type']})" if n in a_objs else n
            for n in diff["added"][:_MAX_LISTED]
        ]
        lines.append(f"+ added ({len(diff['added'])}): " + ", ".join(shown) + _more(diff["added"]))
    if diff["removed"]:
        lines.append(
            f"- removed ({len(diff['removed'])}): "
            + ", ".join(diff["removed"][:_MAX_LISTED]) + _more(diff["removed"])
        )
    if diff["changed"]:
        lines.append(f"~ changed ({len(diff['changed'])}):")
        for name, fields in itertools.islice(diff["changed"].items(), _MAX_LISTED):
            parts = [f"{k} {_fmt(v[0])} -> {_fmt(v[1])}" for k, v in fields.items()]
            lines.append(f"    {name}: " + "; ".join(parts))
        if len(diff["changed"]) > _MAX_LISTED:
            lines.append(f"    ... and {len(diff['changed']) - _MAX_LISTED} more")
    if diff["scene"]:
        parts = [f"{k} {_fmt(v[0])} -> {_fmt(v[1])}" for k, v in diff["scene"].items()]
        lines.append("~ scene: " + "; ".join(parts))
    return "\n".join(lines)


def _more(items: list) -> str:
    return f", ... (+{len(items) - _MAX_LISTED})" if len(items) > _MAX_LISTED else ""


def _fmt(value: Any) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_fmt(v) for v in value) + "]"
    if isinstance(value, float):
        return f"{value:g}"
    return repr(value) if isinstance(value, str) else str(value)
