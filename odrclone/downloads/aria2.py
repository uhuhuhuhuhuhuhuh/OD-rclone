from __future__ import annotations

import itertools

import httpx


class Aria2Client:
    def __init__(self, rpc_url: str, secret: str | None = None):
        self.rpc_url = rpc_url
        self.secret = secret
        self._ids = itertools.count(1)

    async def call(self, method: str, params: list | None = None):
        params = list(params or [])
        if self.secret:
            params.insert(0, f"token:{self.secret}")
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": f"aria2.{method}", "params": params}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self.rpc_url, json=payload)
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                raise RuntimeError(data["error"])
            return data.get("result")

    async def add_uri(self, url: str, directory: str, filename: str) -> str:
        return await self.call("addUri", [[url], {"dir": directory, "out": filename, "continue": "true"}])

    async def tell_status(self, gid: str):
        return await self.call("tellStatus", [gid, ["status", "totalLength", "completedLength", "downloadSpeed", "errorMessage"]])
