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


def build_config_from_options(options: dict[str, Any]) -> Config:
    """Merge add-on options into a Config suitable for HA-only mode."""
    config = Config()
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

    # Optional prefix hint (defaults already cover play keywords).
    prefixes = str(options.get("command_prefixes") or "").strip()
    if prefixes:
        config.keywords_play = prefixes

    config.init()
    _ensure_dirs(
        config.music_path,
        config.download_path,
        config.temp_path,
        config.cache_dir,
        config.conf_path,
    )
    return config


async def async_main() -> None:
    options = _load_options()
    conversation_entity = str(options.get("conversation_entity") or "").strip()
    if not conversation_entity:
        raise SystemExit(
            "options.conversation_entity is required "
            "(e.g. sensor.xiaomi_l05c_xxxx_conversation)"
        )

    media_player = str(options.get("media_player") or "").strip()
    poll_interval = float(options.get("poll_interval_seconds") or 1.0)

    config = build_config_from_options(options)

    # Import HTTP stack after config paths exist.
    from xiaomusic.api import HttpInit
    from xiaomusic.api import app as HttpApp
    import uvicorn

    xiaomusic = XiaoMusic(config)
    # Setting.json must not drop HA mode / virtual device.
    xiaomusic.config.playback_backend = "ha"
    if HA_DID not in xiaomusic.config.devices:
        xiaomusic.config.devices[HA_DID] = Device(
            did=HA_DID,
            device_id=HA_DEVICE_ID,
            hardware="HA",
            name="HA Speaker",
        )
    xiaomusic.config.mi_did = HA_DID
    xiaomusic.device_manager._update_devices()

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

    ha_conversation = HaConversationPoller(
        conversation_entity=conversation_entity,
        did=HA_DID,
        poll_interval_seconds=poll_interval,
        logger=xiaomusic.log,
    )
    xiaomusic.ha_conversation = ha_conversation

    HttpInit(xiaomusic)

    uvicorn_config = uvicorn.Config(
        HttpApp,
        host="0.0.0.0",
        port=int(config.port),
        log_level="debug" if config.verbose else "info",
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
        "XiaoMusic HA mode: conversation=%s media_player=%s music_url=%s:%s",
        conversation_entity,
        media_player or "(auto)",
        config.hostname,
        config.public_port,
    )
    await server.serve()
    await ha_player.close()
    await ha_conversation.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [ha] [%(levelname)s] %(message)s",
    )
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
