"""
event_bus.py
EventBus for pub-sub event distribution (graph mutation notifications,
live SSE frontend canvas sync, vector re-indexing).
"""
from __future__ import annotations
import asyncio
import json
from typing import Dict, List, Set, Any, Callable


class EventBus:
    def __init__(self):
        self._subscribers: List[asyncio.Queue] = []
        self._callbacks: List[Callable[[Dict[str, Any]], None]] = []

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]):
        """Subscribe a synchronous callback function."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def register_async_queue(self) -> asyncio.Queue:
        """Register an async Queue for SSE event streaming."""
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unregister_async_queue(self, queue: asyncio.Queue):
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def publish(self, event_data: Dict[str, Any]):
        """Publish an event to all subscribers and callbacks."""
        # 1. Execute sync callbacks
        for cb in self._callbacks:
            try:
                cb(event_data)
            except Exception as e:
                print(f"[EventBus] Callback error: {e}")

        # 2. Push to async queues
        for q in list(self._subscribers):
            try:
                q.put_nowait(event_data)
            except Exception:
                pass


# Global EventBus instance
GLOBAL_EVENT_BUS = EventBus()
