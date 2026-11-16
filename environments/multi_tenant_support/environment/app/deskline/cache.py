"""Small in-process LRU cache for hot records (ticket views, tenant rows)."""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Callable, Generic, Hashable, TypeVar

T = TypeVar("T")


class RecordCache(Generic[T]):
    def __init__(self, max_entries: int = 256):
        self.max_entries = max(1, max_entries)
        self._entries: "OrderedDict[Hashable, T]" = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: Hashable) -> T | None:
        if key in self._entries:
            self._entries.move_to_end(key)
            self.hits += 1
            return self._entries[key]
        self.misses += 1
        return None

    def put(self, key: Hashable, value: T) -> T:
        self._entries[key] = value
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        return value

    def get_or_load(self, key: Hashable, loader: Callable[[], T]) -> T:
        cached = self.get(key)
        if cached is not None:
            return cached
        return self.put(key, loader())

    def invalidate(self, key: Hashable) -> None:
        self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def stats(self) -> dict[str, Any]:
        return {"entries": len(self._entries), "hits": self.hits, "misses": self.misses}
