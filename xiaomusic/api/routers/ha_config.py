"""HA add-on config UI mounted under /ha-config (keeps original / UI intact)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from xiaomusic import ha_config_ui as ha_ui

# No HTTP basic auth — used via HA Ingress / local LAN.
router = APIRouter(prefix="/ha-config", tags=["HA 配置"])


@router.get("", include_in_schema=False)
async def ha_config_redirect():
    return RedirectResponse(url="/ha-config/", status_code=307)


@router.get("/", response_class=HTMLResponse)
async def ha_config_page():
    return HTMLResponse(ha_ui.page_html(music_ui_href="../static/default/index.html"))


@router.get("/api/status")
async def ha_config_status():
    return ha_ui.status()


@router.get("/api/log")
async def ha_config_log():
    return {"ok": True, "text": ha_ui.read_log_tail()}


@router.post("/api/options")
async def ha_config_save(request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw = body.get("options") if isinstance(body.get("options"), dict) else body
    try:
        result = ha_ui.save_options(raw, restart=bool(body.get("restart")))
        return JSONResponse(ha_ui.enrich_result(result))
    except ValueError as err:
        return JSONResponse({"ok": False, "error": str(err)}, status_code=400)
    except Exception as err:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(err)}, status_code=500)


@router.post("/api/test/play")
async def ha_config_test_play(request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    try:
        if body:
            ha_ui.save_options(body, restart=False)
        result = ha_ui.test_play()
        return JSONResponse(
            ha_ui.enrich_result(result),
            status_code=200 if result.get("ok") else 400,
        )
    except ValueError as err:
        return JSONResponse({"ok": False, "error": str(err)}, status_code=400)
    except Exception as err:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(err)}, status_code=500)


@router.post("/api/test/stop")
async def ha_config_test_stop():
    try:
        result = ha_ui.test_stop()
        return JSONResponse(
            ha_ui.enrich_result(result),
            status_code=200 if result.get("ok") else 400,
        )
    except Exception as err:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(err)}, status_code=500)
