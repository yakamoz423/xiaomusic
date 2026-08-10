#!/usr/bin/env python3
"""XiaoMusic HA config UI (same page as Ingress /ha-config on :8090).

Default port 8109 — avoid clashing with XiaoAir / other addons on :8099
when host_network is enabled.
"""
from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

# Allow importing xiaomusic package from /app
sys.path.insert(0, "/app")

from xiaomusic import ha_config_ui as ha_ui  # noqa: E402

UI_PORT = int(os.environ.get("XIAOMUSIC_UI_PORT", "8109"))
# Standalone page: music UI is on host port 8090 (Ingress / direct).
MUSIC_UI_HREF = os.environ.get(
    "XIAOMUSIC_MUSIC_UI_HREF",
    "http://homeassistant.local:8090/static/default/index.html",
)


class UIHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[ui] {self.address_string()} {fmt % args}", flush=True)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def _send_json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in ("/", "/index.html", "/ha-config"):
            self._send_html(ha_ui.page_html(music_ui_href=MUSIC_UI_HREF))
            return
        if path.endswith("/api/status") or path == "/api/status":
            self._send_json(200, ha_ui.status())
            return
        if path.endswith("/api/log") or path == "/api/log":
            self._send_json(200, {"ok": True, "text": ha_ui.read_log_tail()})
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        try:
            body = self._read_json()
            if path.endswith("/api/options") or path == "/api/options":
                raw = body.get("options") if isinstance(body.get("options"), dict) else body
                result = ha_ui.save_options(raw, restart=bool(body.get("restart")))
                self._send_json(200 if result.get("ok") else 400, ha_ui.enrich_result(result))
                return
            if path.endswith("/api/test/play") or path == "/api/test/play":
                if body:
                    try:
                        ha_ui.save_options(body, restart=False)
                    except Exception as err:  # noqa: BLE001
                        self._send_json(400, {"ok": False, "error": str(err)})
                        return
                result = ha_ui.test_play()
                self._send_json(
                    200 if result.get("ok") else 400,
                    ha_ui.enrich_result(result),
                )
                return
            if path.endswith("/api/test/stop") or path == "/api/test/stop":
                result = ha_ui.test_stop()
                self._send_json(
                    200 if result.get("ok") else 400,
                    ha_ui.enrich_result(result),
                )
                return
        except ValueError as err:
            self._send_json(400, {"ok": False, "error": str(err)})
            return
        except Exception as err:  # noqa: BLE001
            self._send_json(500, {"ok": False, "error": str(err)})
            return
        self.send_error(404)


def main() -> None:
    if not os.environ.get("SUPERVISOR_TOKEN"):
        print("WARNING: SUPERVISOR_TOKEN missing", flush=True)
    try:
        server = ThreadingHTTPServer(("0.0.0.0", UI_PORT), UIHandler)
    except OSError as exc:
        # Port taken (e.g. another addon) — do not crash-loop s6.
        print(
            f"WARNING: cannot bind :{UI_PORT} ({exc}); "
            "HA config remains available via Ingress /ha-config. Sleeping.",
            flush=True,
        )
        while True:
            time.sleep(3600)
        return
    print(f"XiaoMusic HA config UI listening on :{UI_PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
