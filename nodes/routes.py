"""HTTP routes for the node's "connect a drive" panel (see cloud_drive/connect.py).

GET  /snacknodes/drive/{name}             status and form fields (never secrets)
POST /snacknodes/drive/{name}/connect     JSON {field: value}: check, then store
POST /snacknodes/drive/{name}/oauth       start the Google sign-in (link + code)
POST /snacknodes/drive/{name}/disconnect  forget the stored credentials and vault keys
GET  /snacknodes/vault/{name}             whether this drive has a vault (location only, never keys)
POST /snacknodes/vault/{name}/create      JSON {path, password}: create a vault there and keep its keys
POST /snacknodes/vault/{name}/unlock      JSON {path, password}: open an existing vault
POST /snacknodes/vault/{name}/forget      forget the vault keys (the files on the drive stay)
"""

from __future__ import annotations

import asyncio
import logging

from aiohttp import web

from ..cloud_drive.connect import Connector

logger = logging.getLogger(__name__)
_connector = Connector()


def _run(fn, *args):
    return asyncio.get_running_loop().run_in_executor(None, fn, *args)


async def _call(request: web.Request, action: str) -> web.Response:
    name = request.match_info["name"]
    if name not in _connector.providers:
        return web.json_response({"error": {"zh": "不支持的网盘", "en": "Unknown drive", "detail": name}},
                                 status=404)
    try:
        if action == "status":
            return web.json_response(await _run(_connector.status, name))
        if action == "connect":
            body = await request.json()
            return web.json_response(await _run(_connector.connect, name, body if isinstance(body, dict) else {}))
        if action == "oauth":
            return web.json_response(await _run(_connector.oauth_start, name))
        if action == "disconnect":
            return web.json_response(await _run(_connector.disconnect, name))
        if action == "vault_status":
            return web.json_response(await _run(_connector.vault_status, name))
        if action in ("vault_create", "vault_unlock"):
            body = await request.json()
            fn = _connector.vault_create if action == "vault_create" else _connector.vault_unlock
            return web.json_response(await _run(fn, name, body if isinstance(body, dict) else {}))
        return web.json_response(await _run(_connector.vault_forget, name))
    except Exception as e:  # noqa: BLE001 - explained on the node
        logger.warning("SnackNodes: %s %s failed: %s", action, name, e)  # never logs the password
        explain = _connector.vault_error if action.startswith("vault") else _connector.error
        return web.json_response({"error": explain(name, e)}, status=400)


def register(routes: web.RouteTableDef) -> None:
    routes.get("/snacknodes/drive/{name}")(lambda r: _call(r, "status"))
    for action in ("connect", "oauth", "disconnect"):
        routes.post(f"/snacknodes/drive/{{name}}/{action}")(lambda r, a=action: _call(r, a))
    routes.get("/snacknodes/vault/{name}")(lambda r: _call(r, "vault_status"))
    for action in ("create", "unlock", "forget"):
        routes.post(f"/snacknodes/vault/{{name}}/{action}")(lambda r, a=action: _call(r, "vault_" + a))
