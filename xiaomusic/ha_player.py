"""Home Assistant Supervisor API helpers for media_player playback."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Any
from urllib.parse import urlparse

import aiohttp

HA_API_URL = os.environ.get("HA_API_URL", "http://supervisor/core/api")
DEFAULT_MEDIA_CONTENT_TYPE = "music"

log = logging.getLogger("xiaomusic.ha_player")


def get_supervisor_token() -> str | None:
    return os.environ.get("SUPERVISOR_TOKEN")


def get_local_ip() -> str:
    """Best-effort LAN IP via UDP connect (no packets sent)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def parse_music_public_base(base: str, default_port: int) -> tuple[str, int]:
    """Split music_public_base into (hostname_with_scheme, public_port)."""
    base = (base or "").strip().rstrip("/")
    if not base:
        return f"http://{get_local_ip()}", default_port
    if "://" not in base:
        base = f"http://{base}"
    parsed = urlparse(base)
    scheme = parsed.scheme or "http"
    host = parsed.hostname or get_local_ip()
    port = parsed.port or default_port
    return f"{scheme}://{host}", port


class HaPlayer:
    """Play / stop via Home Assistant media_player services."""

    def __init__(
        self,
        media_player: str = "",
        media_content_type: str = DEFAULT_MEDIA_CONTENT_TYPE,
        session: aiohttp.ClientSession | None = None,
        logger: logging.Logger | None = None,
    ):
        self.media_player = (media_player or "").strip()
        self.media_content_type = media_content_type or DEFAULT_MEDIA_CONTENT_TYPE
        self._session = session
        self._owns_session = session is None
        self.log = logger or log
        self._resolved_entity: str | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    def _headers(self) -> dict[str, str]:
        token = get_supervisor_token()
        if not token:
            raise RuntimeError("SUPERVISOR_TOKEN missing")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[bool, Any]:
        session = await self._ensure_session()
        url = f"{HA_API_URL.rstrip('/')}/{path.lstrip('/')}"
        try:
            async with session.request(
                method,
                url,
                headers=self._headers(),
                json=json_body,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    return False, f"HTTP {resp.status}: {text[:300]}"
                if not text:
                    return True, None
                try:
                    return True, await resp.json(content_type=None)
                except Exception:
                    return True, text
        except Exception as exc:
            return False, str(exc)

    async def call_service(
        self, service: str, data: dict[str, Any]
    ) -> tuple[bool, Any]:
        return await self._request("POST", f"services/{service}", data)

    async def get_state(self, entity_id: str) -> dict[str, Any] | None:
        ok, data = await self._request("GET", f"states/{entity_id}")
        if not ok or not isinstance(data, dict):
            return None
        return data

    async def get_states(self) -> list[dict[str, Any]]:
        ok, data = await self._request("GET", "states")
        if not ok or not isinstance(data, list):
            self.log.warning("get_states failed: %s", data)
            return []
        return data

    async def resolve_media_player(self) -> str:
        if self.media_player and self.media_player.lower() not in ("", "auto"):
            self._resolved_entity = self.media_player
            return self.media_player
        if self._resolved_entity:
            return self._resolved_entity

        states = await self.get_states()
        players = [
            s for s in states if str(s.get("entity_id", "")).startswith("media_player.")
        ]

        def score(entity: dict[str, Any]) -> tuple[int, str]:
            eid = entity.get("entity_id", "")
            attrs = entity.get("attributes") or {}
            name = str(attrs.get("friendly_name") or "")
            hay = f"{eid} {name}".lower()
            pts = 0
            if "xiaoai" in hay or "xiaomi" in hay or "小爱" in hay:
                pts += 100
            if "play_control" in hay:
                pts += 50
            if entity.get("state") not in ("unavailable", "unknown"):
                pts += 10
            return (-pts, eid)

        players.sort(key=score)
        if not players:
            raise RuntimeError("No media_player.* entity found")
        self._resolved_entity = players[0]["entity_id"]
        self.log.info("Auto-selected media_player: %s", self._resolved_entity)
        return self._resolved_entity

    async def play_url(self, url: str, entity_id: str | None = None) -> bool:
        entity = entity_id or await self.resolve_media_player()
        # music_library may return host:port without scheme
        if url and not url.startswith(("http://", "https://")):
            url = f"http://{url}" if "://" not in url else url
        # Refuse empty music root URLs produced by missing local files.
        stripped = (url or "").rstrip("/")
        if not url or stripped.endswith("/music"):
            self.log.error("refuse play_media with empty/invalid url: %r", url)
            return False

        # xiaomi_miot: type "music"/"mp3"/... → async_play_music (placeholder audio_id);
        # other types (e.g. "1") → player_play_url which works better on some L05C.
        # Try play_url path first, then configured/music fallback.
        content_types: list[str] = []
        for candidate in ("1", self.media_content_type, "music"):
            c = str(candidate or "").strip()
            if c and c not in content_types:
                content_types.append(c)

        last_ok = False
        for ctype in content_types:
            self.log.info("play_media %s type=%s <- %s", entity, ctype, url)
            ok, detail = await self.call_service(
                "media_player/play_media",
                {
                    "entity_id": entity,
                    "media_content_id": url,
                    "media_content_type": ctype,
                },
            )
            if not ok:
                self.log.error("play_media type=%s failed: %s", ctype, detail)
                continue
            last_ok = True
            self.log.info("play_media type=%s accepted (%s)", ctype, detail)

            await asyncio.sleep(1.0)
            state = await self.get_state(entity)
            title = ""
            content_id = ""
            ha_state = ""
            if state:
                attrs = (
                    state.get("attributes")
                    if isinstance(state.get("attributes"), dict)
                    else {}
                )
                title = str(attrs.get("media_title") or "")
                content_id = str(attrs.get("media_content_id") or "")
                ha_state = str(state.get("state") or "")
                self.log.info(
                    "post-play type=%s state=%s vol=%s content_id=%s title=%s",
                    ctype,
                    ha_state,
                    attrs.get("volume_level"),
                    content_id,
                    title,
                )
            # If still stuck on XiaoAI hold music, try next content type.
            if title.startswith("请欣赏") or content_id in (
                "2838397602828911155",
            ):
                self.log.warning(
                    "play_media type=%s did not take over (still 请欣赏/hold); try next",
                    ctype,
                )
                continue
            return True

        return last_ok

    async def stop(self, entity_id: str | None = None) -> bool:
        """Optional interrupt. Prefer pause; media_stop often 500s on MIOT."""
        entity = entity_id or await self.resolve_media_player()
        payload = {"entity_id": entity}
        attempts = (
            "media_player/media_pause",
            "media_player/media_stop",
            "media_player/turn_off",
        )
        for service in attempts:
            ok, detail = await self.call_service(service, payload)
            if ok:
                self.log.info("stop via %s (%s)", service, detail)
                return True
            self.log.warning("stop via %s failed: %s", service, detail)
        self.log.warning("could not stop media_player (ignored)")
        return False
