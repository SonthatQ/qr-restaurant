import asyncio
import json
from typing import Dict, Set
from fastapi import WebSocket


class WSManager:
    def __init__(self) -> None:
        self._staff: Set[WebSocket] = set()
        self._tables: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect_staff(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._staff.add(ws)

    async def disconnect_staff(self, ws: WebSocket) -> None:
        async with self._lock:
            self._staff.discard(ws)

    async def connect_table(self, table_token: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._tables.setdefault(table_token, set()).add(ws)

    async def disconnect_table(self, table_token: str, ws: WebSocket) -> None:
        async with self._lock:
            if table_token in self._tables:
                self._tables[table_token].discard(ws)
                if not self._tables[table_token]:
                    self._tables.pop(table_token, None)

    async def _safe_send(self, ws: WebSocket, payload: dict) -> bool:
        try:
            await ws.send_text(json.dumps(payload, ensure_ascii=False))
            return True
        except Exception:
            return False

    def broadcast_staff_json(self, payload: dict) -> None:
        asyncio.create_task(self._broadcast_staff(payload))

    async def _broadcast_staff(self, payload: dict) -> None:
        async with self._lock:
            targets = list(self._staff)
        dead = []
        for ws in targets:
            ok = await self._safe_send(ws, payload)
            if not ok:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._staff.discard(ws)

    def broadcast_table_json(self, table_token: str, payload: dict) -> None:
        asyncio.create_task(self._broadcast_table(table_token, payload))

    async def _broadcast_table(self, table_token: str, payload: dict) -> None:
        async with self._lock:
            targets = list(self._tables.get(table_token, set()))
        dead = []
        for ws in targets:
            ok = await self._safe_send(ws, payload)
            if not ok:
                dead.append(ws)
        if dead:
            async with self._lock:
                s = self._tables.get(table_token)
                if s:
                    for ws in dead:
                        s.discard(ws)
                    if not s:
                        self._tables.pop(table_token, None)


ws_manager = WSManager()
