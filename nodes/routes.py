"""HTTP routes for the node's "connect a drive" panel (see cloud_drive/connect.py).

GET  /snacknodes/drive/{name}             status and form fields (never secrets)
POST /snacknodes/drive/{name}/connect     JSON {field: value}: check, then store
POST /snacknodes/drive/{name}/oauth       start the Google sign-in (link + code)
POST /snacknodes/drive/{name}/disconnect  forget the stored credentials and vault keys
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
        return web.json_response(await _run(_connector.disconnect, name))
    except Exception as e:  # noqa: BLE001 - explained in the panel
        logger.warning("SnackNodes: %s %s failed: %s", action, name, e)
        return web.json_response({"error": _connector.error(name, e)}, status=400)


def register(routes: web.RouteTableDef) -> None:
    routes.get("/snacknodes/drive/{name}")(lambda r: _call(r, "status"))
    for action in ("connect", "oauth", "disconnect"):
        routes.post(f"/snacknodes/drive/{{name}}/{action}")(lambda r, a=action: _call(r, a))
