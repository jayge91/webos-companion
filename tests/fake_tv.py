"""A minimal in-process stand-in for a WebOS TV's SSAP websocket endpoint."""

from __future__ import annotations

import asyncio
import json

from websockets.asyncio.server import serve


class FakeTV:
    def __init__(
        self,
        *,
        known_key: str | None = None,
        new_key: str = "NEWKEY-abc123",
        pair_delay: float = 0.0,
        power_state: str = "Active",
        drop_after: int | None = None,
        error_uris: set[str] | None = None,
    ) -> None:
        self.known_key = known_key
        self.new_key = new_key
        self.pair_delay = pair_delay
        self.power_state = power_state
        self.drop_after = drop_after
        # substrings of URIs the TV should answer with an error frame
        self.error_uris = error_uris or set()

        self.requests: list[dict] = []       # every request frame received
        self.uris: list[str] = []            # convenience: just the uris
        self.connections = 0
        self._server = None
        self.host = "127.0.0.1"
        self.port = 0

    async def __aenter__(self) -> "FakeTV":
        self._server = await serve(self._handle, self.host, 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc) -> None:
        self._server.close()
        await self._server.wait_closed()

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    async def _handle(self, ws) -> None:
        self.connections += 1
        handled = 0
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") == "register":
                await self._register(ws, msg)
                continue

            self.requests.append(msg)
            self.uris.append(msg.get("uri", ""))
            await self._respond(ws, msg)

            handled += 1
            if self.drop_after is not None and handled >= self.drop_after:
                await ws.close()
                return

    async def _register(self, ws, msg) -> None:
        key = (msg.get("payload") or {}).get("client-key")
        if not key:
            await ws.send(
                json.dumps(
                    {
                        "type": "response",
                        "id": "register_0",
                        "payload": {"pairingType": "PROMPT", "returnValue": True},
                    }
                )
            )
            if self.pair_delay:
                await asyncio.sleep(self.pair_delay)
            key = self.new_key
        elif self.known_key is not None and key != self.known_key:
            await ws.send(
                json.dumps(
                    {"type": "error", "id": "register_0", "error": "401 rejected pairing"}
                )
            )
            return
        await ws.send(
            json.dumps(
                {
                    "type": "registered",
                    "id": "register_0",
                    "payload": {"client-key": key},
                }
            )
        )

    async def _respond(self, ws, msg) -> None:
        uri = msg.get("uri", "")
        if any(frag in uri for frag in self.error_uris):
            await ws.send(
                json.dumps(
                    {"type": "error", "id": msg.get("id", ""), "error": "500 Application error"}
                )
            )
            return
        payload: dict = {"returnValue": True}
        if uri.endswith("getPowerState"):
            payload["state"] = self.power_state
        await ws.send(
            json.dumps({"type": "response", "id": msg.get("id", ""), "payload": payload})
        )
