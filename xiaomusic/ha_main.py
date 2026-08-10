"""Home Assistant add-on entry: conversation → commands → HA play_media."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from pathlib import Path
from typing import Any

from xiaomusic.config import Config, Device
from xiaomusic.ha_conversation import HaConversationPoller
from xiaomusic.ha_player import HaPlayer, parse_music_public_base
from xiaomusic.xiaomusic import XiaoMusic

HA_DID = "ha"
HA_DEVICE_ID = "HA-DEVICE"
OPTIONS_PATHS = (
    Path("/data/options.json"),
    Path("/addon_config/options.json"),
)


def _load_options() -> dict[str, Any]:
    for path in OPTIONS_PATHS:
        if path.is_file():
            with path.open(encoding="utf-8") as fh:
                return json.load(fh)
    env_opts = os.environ.get("XIAOMUSIC_HA_OPTIONS")
    if env_opts:
        return json.loads(env_opts)
    return {}


def _ensure_dirs(*paths: str) -> None:
    for path in paths:
        if path:
            os.makedirs(path, exist_ok=True)


def apply_ha_options(config: Config, options: dict[str, Any]) -> None:
    """Apply / re-apply add-on options onto Config (after setting.json load)."""
    config.playback_backend = "ha"
    config.verbose = bool(options.get("verbose", False))
    config.disable_download = bool(options.get("disable_download", False))

    search_prefix = str(options.get("search_prefix") or "bilisearch:").strip()
    if search_prefix:
        config.search_prefix = search_prefix

    # Paths: prefer HA media share, fall back to /app/music + /data conf.
    media_root = "/media/xiaomusic"
    if not os.path.isdir("/media"):
        media_root = "/app/music"
    config.music_path = os.environ.get("XIAOMUSIC_MUSIC_PATH", media_root)
    config.download_path = os.path.join(config.music_path, "download")
    config.temp_path = os.path.join(config.music_path, "tmp")
    config.cache_dir = os.path.join(config.music_path, "cache")
    config.conf_path = os.environ.get("XIAOMUSIC_CONF_PATH", "/data/xiaomusic_conf")
    config.log_file = os.path.join(config.conf_path, "xiaomusic.log.txt")

    listen_port = int(os.environ.get("XIAOMUSIC_PORT", "8090"))
    config.port = listen_port
    hostname, public_port = parse_music_public_base(
        str(options.get("music_public_base") or ""),
        listen_port,
    )
    config.hostname = hostname
    config.public_port = public_port

    config.ffmpeg_location = os.environ.get(
        "XIAOMUSIC_FFMPEG_LOCATION", "/app/ffmpeg/bin"
    )
    # Prefer edge-tts so HA mode never needs MiNA TTS.
    if not config.edge_tts_voice:
        config.edge_tts_voice = "zh-CN-XiaoyiNeural"

    # Ingress / LAN web UI should not require HTTP basic auth in add-on mode.
    config.disable_httpauth = True

    # Virtual device for command routing.
    config.mi_did = HA_DID
    config.devices = {
        HA_DID: Device(
            did=HA_DID,
            device_id=HA_DEVICE_ID,
            hardware="HA",
            name="HA Speaker",
        )
    }

    # command_prefixes maps to keywords_play (comma-separated).
    # Put custom prefixes first so short ones like「播放」beat longer defaults.
    prefixes = str(options.get("command_prefixes") or "").strip()
    if prefixes:
        config.keywords_play = prefixes
        config.init()
        # Ensure custom play keys are tried early in fuzzy match order.
        custom = [k for k in prefixes.split(",") if k]
        rest = [k for k in config.key_match_order if k not in custom]
        config.key_match_order = custom + rest
    else:
        config.init()

    _ensure_dirs(
        config.music_path,
        config.download_path,
        config.temp_path,
        config.cache_dir,
        config.conf_path,
    )


def build_config_from_options(options: dict[str, Any]) -> Config:
    """Merge add-on options into a Config suitable for HA-only mode."""
    config = Config()
    apply_ha_options(config, options)
    return config


async def async_main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [ha] [%(levelname)s] %(message)s",
    )

    options = _load_options()
    conversation_entity = str(options.get("conversation_entity") or "").strip()
    media_player = str(options.get("media_player") or "").strip()
    poll_interval = float(options.get("poll_interval_seconds") or 1.0)

    config = build_config_from_options(options)

    import uvicorn

    from xiaomusic.api import HttpInit
    from xiaomusic.api import app as HttpApp

    xiaomusic = XiaoMusic(config)
    # setting.json may overwrite keywords_* / devices — re-apply add-on options.
    apply_ha_options(xiaomusic.config, options)
    xiaomusic.device_manager._update_devices()
    xiaomusic.log.info(
        "HA options applied: keywords_play=%r search_prefix=%r "
        "disable_download=%s key_match_order_head=%s",
        xiaomusic.config.keywords_play,
        xiaomusic.config.search_prefix,
        xiaomusic.config.disable_download,
        xiaomusic.config.key_match_order[:8],
    )

    ha_player = HaPlayer(
        media_player=media_player,
        logger=xiaomusic.log,
    )
    xiaomusic.ha_player = ha_player
    try:
        resolved = await ha_player.resolve_media_player()
        xiaomusic.log.info("HA media_player ready: %s", resolved)
    except Exception as exc:
        xiaomusic.log.warning("media_player resolve deferred: %s", exc)

    # Always attach poller so run_forever can start; empty entity waits in run_loop.
    ha_conversation = HaConversationPoller(
        conversation_entity=conversation_entity,
        did=HA_DID,
        poll_interval_seconds=poll_interval,
        logger=xiaomusic.log,
        options_loader=_load_options,
    )
    xiaomusic.ha_conversation = ha_conversation

    HttpInit(xiaomusic)

    uvicorn_config = uvicorn.Config(
        HttpApp,
        host="0.0.0.0",
        port=int(xiaomusic.config.port),
        log_level="debug" if xiaomusic.config.verbose else "info",
    )
    server = uvicorn.Server(uvicorn_config)

    shutdown = False

    def _handle_exit(signum, frame):
        nonlocal shutdown
        if not shutdown:
            shutdown = True
            xiaomusic.log.info("Shutdown signal %s", signum)
            server.should_exit = True

    signal.signal(signal.SIGINT, _handle_exit)
    signal.signal(signal.SIGTERM, _handle_exit)

    xiaomusic.log.info(
        "XiaoMusic HA mode: conversation=%s media_player=%s music_url=%s:%s "
        "(Ingress web UI :%s , HA config /ha-config or :8099)",
        conversation_entity or "(pending via /ha-config)",
        media_player or "(auto)",
        xiaomusic.config.hostname,
        xiaomusic.config.public_port,
        xiaomusic.config.port,
    )
    await server.serve()
    await ha_player.close()
    await ha_conversation.close()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
