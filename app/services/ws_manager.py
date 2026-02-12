from __future__ import annotations
import asyncio
import json
from typing import Dict, Set
from fastapi import WebSocket


class WSManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._groups: Dict[str, Set[WebSocket]] = {}

    async def connect(self, group: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._groups.setdefault(group, set()).add(ws)

    async def disconnect(self, group: str, ws: WebSocket) -> None:
        async with self._lock:
            if group in self._groups and ws in self._groups[group]:
                self._groups[group].remove(ws)
                if not self._groups[group]:
                    self._groups.pop(group, None)

    async def broadcast(self, group: str, message: dict) -> None:
        payload = json.dumps(message, ensure_ascii=False)
        async with self._lock:
            targets = list(self._groups.get(group, set()))
        dead = []
        for ws in targets:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    if group in self._groups and ws in self._groups[group]:
                        self._groups[group].remove(ws)

    async def broadcast_multi(self, groups: list[str], message: dict) -> None:
        for g in groups:
            await self.broadcast(g, message)


ws_manager = WSManager()
