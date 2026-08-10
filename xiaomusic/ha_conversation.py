"""Poll Home Assistant MIOT conversation sensor for voice queries."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

HA_API_URL = os.environ.get("HA_API_URL", "http://supervisor/core/api")

OnQueryCallback = Callable[..., Awaitable[None]]
OptionsLoader = Callable[[], dict[str, Any]]

log = logging.getLogger("xiaomusic.ha_conversation")


class HaConversationPoller:
    """Watch a conversation sensor and invoke on_query(did, query, ctrl_panel)."""

    def __init__(
        self,
        conversation_entity: str,
        did: str,
        poll_interval_seconds: float = 1.0,
        session: aiohttp.ClientSession | None = None,
        logger: logging.Logger | None = None,
        options_loader: OptionsLoader | None = None,
    ):
        self.conversation_entity = (conversation_entity or "").strip()
        self.did = did
        self.poll_interval = max(0.2, float(poll_interval_seconds or 1.0))
        self._session = session
        self._owns_session = session is None
        self.log = logger or log
        self._last_fingerprint: str | None = None
        self._last_query: str = ""
        self._options_loader = options_loader

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    def _headers(self) -> dict[str, str]:
        token = os.environ.get("SUPERVISOR_TOKEN")
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
                timeout=aiohttp.ClientTimeout(total=20),
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

    async def update_entity(self) -> None:
        ok, detail = await self._request(
            "POST",
            "services/homeassistant/update_entity",
            {"entity_id": self.conversation_entity},
        )
        if not ok:
            self.log.debug("update_entity failed: %s", detail)

    async def fetch_state(self) -> dict[str, Any] | None:
        ok, data = await self._request("GET", f"states/{self.conversation_entity}")
        if not ok or not isinstance(data, dict):
            self.log.warning("Failed to read %s: %s", self.conversation_entity, data)
            return None
        return data

    @staticmethod
    def extract_query(state: dict[str, Any]) -> str:
        attrs = state.get("attributes") or {}
        for key in ("query", "content", "text", "message", "conversation"):
            val = attrs.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        raw = state.get("state")
        if isinstance(raw, str):
            raw = raw.strip()
            if raw and raw.lower() not in ("unknown", "unavailable", "none", ""):
                return raw
        return ""

    @staticmethod
    def fingerprint(state: dict[str, Any], query: str) -> str:
        attrs = state.get("attributes") or {}
        ts = (
            attrs.get("timestamp")
            or attrs.get("last_changed")
            or attrs.get("time")
            or state.get("last_changed")
            or state.get("last_updated")
            or ""
        )
        return f"{ts}|{query}"

    async def _wait_for_entity(self) -> None:
        """Block until conversation_entity is configured (web UI / options)."""
        while not self.conversation_entity:
            self.log.warning(
                "conversation_entity not set — open Ingress /ha-config "
                "(or :8099) to pick a MIOT conversation sensor"
            )
            await asyncio.sleep(5)
            if self._options_loader is None:
                continue
            try:
                options = self._options_loader() or {}
            except Exception as exc:  # noqa: BLE001
                self.log.debug("options reload failed: %s", exc)
                continue
            entity = str(options.get("conversation_entity") or "").strip()
            if entity:
                self.conversation_entity = entity
                try:
                    self.poll_interval = max(
                        0.2, float(options.get("poll_interval_seconds") or 1.0)
                    )
                except (TypeError, ValueError):
                    pass
                self.log.info("conversation_entity ready: %s", entity)

    async def run_loop(
        self,
        on_query: OnQueryCallback,
        reset_timer: OnQueryCallback | None = None,
    ) -> None:
        await self._wait_for_entity()
        if not self.conversation_entity:
            raise RuntimeError("conversation_entity is required")

        self.log.info(
            "HA conversation poller started entity=%s interval=%.2fs did=%s",
            self.conversation_entity,
            self.poll_interval,
            self.did,
        )

        # Prime fingerprint so we don't replay the last utterance on startup.
        first = await self.fetch_state()
        if first:
            q0 = self.extract_query(first)
            self._last_fingerprint = self.fingerprint(first, q0)
            self._last_query = q0
            self.log.info("Initial conversation fingerprint set (query=%r)", q0)

        while True:
            try:
                await self.update_entity()
                state = await self.fetch_state()
                if state:
                    query = self.extract_query(state)
                    fp = self.fingerprint(state, query)
                    if query and fp != self._last_fingerprint:
                        self.log.info("New conversation query: %r", query)
                        self._last_fingerprint = fp
                        self._last_query = query
                        await on_query(self.did, query, False)
                        if reset_timer:
                            await reset_timer(0, self.did)
            except asyncio.CancelledError:
                self.log.info("HA conversation poller cancelled")
                raise
            except Exception as exc:
                self.log.exception("HA conversation poll error: %s", exc)

            await asyncio.sleep(self.poll_interval)
