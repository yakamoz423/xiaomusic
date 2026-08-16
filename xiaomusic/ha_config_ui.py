"""Shared HA add-on options UI helpers (Ingress + /ha-config)."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any

import requests

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN")
HA_API_URL = os.environ.get("HA_API_URL", "http://supervisor/core/api")
SUPERVISOR_URL = os.environ.get("SUPERVISOR_URL", "http://supervisor")
OPTIONS_FILE = "/data/options.json"
LOG_CANDIDATES = (
    "/data/xiaomusic_conf/xiaomusic.log.txt",
    "/media/xiaomusic/xiaomusic.log.txt",
)

SUPPORT_PLAY_MEDIA = 16384
AUTO_SENTINELS = {"", "auto", "change_me", "media_player.change_me"}

XIAOAI_HINTS = (
    "xiaoai",
    "xiaomi",
    "xiaomusic",
    "wifispeaker",
    "l05c",
    "l06a",
    "lx06",
    "oh2p",
    "小爱",
    "小米",
)

CONVERSATION_HINTS = (
    "conversation",
    "对话",
    "语音",
    "xiaoai",
    "xiaomi",
    "miot",
)

DEFAULT_OPTIONS: dict[str, Any] = {
    "conversation_entity": "",
    "media_player": "",
    "command_prefixes": "播放歌曲,放歌曲,播放本地歌曲,本地播放歌曲",
    "poll_interval_seconds": 1.0,
    "music_public_base": "",
    "disable_download": False,
    "search_prefix": "bilisearch:",
    "verbose": False,
    "enable_yt_dlp_cookies": False,
}

COOKIES_FILENAME = "yt-dlp-cookie.txt"

_lock = threading.Lock()


def cookies_file_path() -> str:
    conf = os.environ.get("XIAOMUSIC_CONF_PATH", "/data/xiaomusic_conf")
    os.makedirs(conf, exist_ok=True)
    return os.path.join(conf, COOKIES_FILENAME)


def inspect_cookies_text(text: str) -> dict[str, Any]:
    """Inspect Netscape cookies.txt without exposing cookie values."""
    has_bilibili = False
    has_buvid3 = False
    has_youtube = False
    line_count = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_") :]
        elif line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        line_count += 1
        domain = parts[0].lower()
        name = parts[5]
        if "bilibili" in domain:
            has_bilibili = True
            if name.lower() == "buvid3":
                has_buvid3 = True
        if "youtube" in domain or "google.com" in domain:
            has_youtube = True
    return {
        "line_count": line_count,
        "has_bilibili": has_bilibili,
        "has_buvid3": has_buvid3,
        "has_youtube": has_youtube,
    }


def cookies_status() -> dict[str, Any]:
    path = cookies_file_path()
    present = os.path.isfile(path) and os.path.getsize(path) > 0
    info: dict[str, Any] = {
        "path": path,
        "present": present,
        "size": os.path.getsize(path) if present else 0,
        "mtime": None,
        "line_count": 0,
        "has_bilibili": False,
        "has_buvid3": False,
        "has_youtube": False,
    }
    if not present:
        return info
    try:
        info["mtime"] = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(path))
        )
        with open(path, encoding="utf-8", errors="replace") as handle:
            info.update(inspect_cookies_text(handle.read()))
    except OSError:
        pass
    return info


def apply_cookies_flag_to_runtime(enabled: bool) -> bool:
    """Hot-patch the running XiaoMusic config when this process hosts it."""
    try:
        from xiaomusic.api.dependencies import _state

        if not _state.is_initialized():
            return False
        _state._xiaomusic.config.enable_yt_dlp_cookies = enabled
        if _state._log:
            _state._log.info(
                "HA cookies flag applied live: enable_yt_dlp_cookies=%s path=%s",
                enabled,
                cookies_file_path(),
            )
        return True
    except Exception:  # noqa: BLE001
        return False


def save_cookies_text(text: str, enable: bool = True) -> dict[str, Any]:
    text = (text or "").replace("\r\n", "\n")
    if not text.strip():
        raise ValueError("cookies 内容为空")
    parsed = inspect_cookies_text(text)
    if int(parsed.get("line_count") or 0) <= 0:
        raise ValueError(
            "不是有效的 Netscape cookies.txt（需要制表符分隔的 cookie 行）"
        )
    path = cookies_file_path()
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")

    live = False
    if enable:
        options = load_options()
        options["enable_yt_dlp_cookies"] = True
        write_options_file(options)
        try:
            supervisor_set_options(options)
        except Exception as err:  # noqa: BLE001
            print(f"warning: supervisor options sync failed: {err}", flush=True)
        live = apply_cookies_flag_to_runtime(True)

    cookies = cookies_status()
    hints = []
    if not cookies.get("has_bilibili"):
        hints.append("未检测到 .bilibili.com，B 站搜索 412 可能仍会失败")
    elif not cookies.get("has_buvid3"):
        hints.append("未检测到 buvid3，建议重新导出（打开一次 bilibili.com 即可）")
    message = f"已保存 cookies（{cookies.get('line_count') or 0} 条）"
    if enable:
        message += "，并已启用 yt-dlp --cookies"
    if live:
        message += "。当前进程已生效，无需重启即可下载。"
    else:
        message += "。请点「保存并重启」让下载进程加载 cookies。"
    if hints:
        message += "。注意: " + "；".join(hints)
    return {
        "ok": True,
        "options": load_options(),
        "cookies": cookies,
        "live": live,
        "message": message,
    }


def ha_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "Content-Type": "application/json",
    }


def load_options() -> dict[str, Any]:
    data: dict[str, Any] = dict(DEFAULT_OPTIONS)
    try:
        with open(OPTIONS_FILE, encoding="utf-8") as handle:
            loaded = json.load(handle)
            if isinstance(loaded, dict):
                data.update(loaded)
    except Exception:  # noqa: BLE001
        pass
    return data


def write_options_file(options: dict[str, Any]) -> None:
    with open(OPTIONS_FILE, "w", encoding="utf-8") as handle:
        json.dump(options, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def supervisor_set_options(options: dict[str, Any]) -> None:
    response = requests.post(
        f"{SUPERVISOR_URL}/addons/self/options",
        headers=ha_headers(),
        json={"options": options},
        timeout=20,
    )
    if response.status_code >= 400:
        response.raise_for_status()


def supervisor_restart() -> None:
    response = requests.post(
        f"{SUPERVISOR_URL}/addons/self/restart",
        headers=ha_headers(),
        timeout=30,
    )
    if response.status_code >= 400:
        response.raise_for_status()


def fetch_all_states() -> list[dict[str, Any]]:
    try:
        response = requests.get(
            f"{HA_API_URL}/states",
            headers=ha_headers(),
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []
    except requests.RequestException:
        return []


def fetch_state(entity_id: str) -> dict[str, Any] | None:
    if not entity_id:
        return None
    try:
        response = requests.get(
            f"{HA_API_URL}/states/{entity_id}",
            headers=ha_headers(),
            timeout=10,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except requests.RequestException:
        return None


def _blob(entity_id: str, attributes: dict[str, Any]) -> str:
    parts = [
        entity_id,
        str(attributes.get("friendly_name") or ""),
        str(attributes.get("model") or ""),
        str(attributes.get("device_class") or ""),
    ]
    return " ".join(parts).lower()


def score_media_player(state: dict[str, Any]) -> int:
    entity_id = str(state.get("entity_id") or "")
    attributes = (
        state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
    )
    ha_state = str(state.get("state") or "unknown")
    blob = _blob(entity_id, attributes)
    score = 0
    if any(hint in blob for hint in XIAOAI_HINTS):
        score += 100
    try:
        supported = attributes.get("supported_features")
        if supported is not None and int(supported) & SUPPORT_PLAY_MEDIA:
            score += 20
    except (TypeError, ValueError):
        pass
    if ha_state not in {"unavailable", "unknown"}:
        score += 10
    if ha_state in {"idle", "paused", "playing", "on", "off", "standby"}:
        score += 5
    if re.search(r"(browser|cast|chromecast|tv|web_browser|youtube)", blob):
        score -= 30
    return score


def score_conversation(state: dict[str, Any]) -> int:
    entity_id = str(state.get("entity_id") or "")
    attributes = (
        state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
    )
    ha_state = str(state.get("state") or "unknown")
    blob = _blob(entity_id, attributes)
    score = 0
    if "conversation" in entity_id.lower():
        score += 120
    if any(hint in blob for hint in CONVERSATION_HINTS):
        score += 40
    if any(hint in blob for hint in XIAOAI_HINTS):
        score += 30
    for key in ("query", "content", "text", "message"):
        if key in attributes:
            score += 25
            break
    if ha_state not in {"unavailable", "unknown"}:
        score += 10
    if entity_id.startswith("sensor."):
        score += 5
    return score


def list_media_players() -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []
    states = [
        s
        for s in fetch_all_states()
        if isinstance(s, dict) and str(s.get("entity_id") or "").startswith("media_player.")
    ]
    for state in sorted(states, key=score_media_player, reverse=True):
        entity_id = str(state.get("entity_id") or "")
        attributes = (
            state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
        )
        choices.append(
            {
                "entity_id": entity_id,
                "friendly_name": attributes.get("friendly_name") or entity_id,
                "state": state.get("state") or "unknown",
                "score": score_media_player(state),
            }
        )
    return choices


def list_conversation_sensors() -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []
    for state in fetch_all_states():
        if not isinstance(state, dict):
            continue
        entity_id = str(state.get("entity_id") or "")
        if not entity_id.startswith("sensor."):
            continue
        score = score_conversation(state)
        if score < 40 and "conversation" not in entity_id.lower():
            continue
        attributes = (
            state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
        )
        choices.append(
            {
                "entity_id": entity_id,
                "friendly_name": attributes.get("friendly_name") or entity_id,
                "state": state.get("state") or "unknown",
                "score": score,
                "query_preview": extract_query(state)[:80],
            }
        )
    choices.sort(key=lambda item: int(item.get("score") or 0), reverse=True)
    return choices


def extract_query(state: dict[str, Any]) -> str:
    attributes = (
        state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
    )
    for key in ("query", "content", "text", "message", "conversation"):
        val = attributes.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    raw = state.get("state")
    if isinstance(raw, str):
        raw = raw.strip()
        if raw and raw.lower() not in ("unknown", "unavailable", "none", ""):
            return raw
    return ""


def normalize_options(raw: dict[str, Any]) -> dict[str, Any]:
    options = dict(DEFAULT_OPTIONS)
    options.update(load_options())
    if not isinstance(raw, dict):
        return options

    conversation = str(
        raw.get("conversation_entity", options["conversation_entity"]) or ""
    ).strip()
    media_player = str(raw.get("media_player", options["media_player"]) or "").strip()
    if media_player.lower() in AUTO_SENTINELS:
        media_player = ""
    if media_player and not media_player.startswith("media_player."):
        raise ValueError("media_player must be media_player.* or empty")
    if conversation and not conversation.startswith("sensor."):
        raise ValueError("conversation_entity must be sensor.*")

    try:
        poll = float(raw.get("poll_interval_seconds", options["poll_interval_seconds"]))
    except (TypeError, ValueError) as err:
        raise ValueError("poll_interval_seconds must be a number") from err
    poll = max(0.2, poll)

    options.update(
        {
            "conversation_entity": conversation,
            "media_player": media_player,
            "command_prefixes": str(
                raw.get("command_prefixes", options["command_prefixes"]) or ""
            ).strip(),
            "poll_interval_seconds": poll,
            "music_public_base": str(
                raw.get("music_public_base", options["music_public_base"]) or ""
            ).strip(),
            "disable_download": bool(
                raw.get("disable_download", options["disable_download"])
            ),
            "search_prefix": str(
                raw.get("search_prefix", options["search_prefix"]) or "bilisearch:"
            ).strip()
            or "bilisearch:",
            "verbose": bool(raw.get("verbose", options["verbose"])),
            "enable_yt_dlp_cookies": bool(
                raw.get("enable_yt_dlp_cookies", options["enable_yt_dlp_cookies"])
            ),
        }
    )
    return options


def _delayed_restart() -> None:
    time.sleep(0.4)
    try:
        supervisor_restart()
    except Exception as err:  # noqa: BLE001
        print(f"warning: restart failed: {err}", flush=True)


def save_options(raw: dict[str, Any], restart: bool = False) -> dict[str, Any]:
    with _lock:
        options = normalize_options(raw)
        write_options_file(options)
        try:
            supervisor_set_options(options)
        except Exception as err:  # noqa: BLE001
            print(f"warning: supervisor options sync failed: {err}", flush=True)

        result: dict[str, Any] = {
            "ok": True,
            "options": options,
            "message": "已保存配置",
            "restarting": False,
        }
        if restart:
            result["message"] = "已保存，正在重启插件以应用配置…"
            result["restarting"] = True
            threading.Thread(target=_delayed_restart, daemon=True).start()
        else:
            apply_cookies_flag_to_runtime(bool(options.get("enable_yt_dlp_cookies")))
        result["cookies"] = cookies_status()
        return result


def call_ha_service(domain: str, service: str, data: dict[str, Any]) -> tuple[bool, str]:
    try:
        response = requests.post(
            f"{HA_API_URL}/services/{domain}/{service}",
            headers=ha_headers(),
            json=data,
            timeout=20,
        )
        if response.status_code >= 400:
            return False, f"HTTP {response.status_code}: {response.text[:300]}"
        return True, "ok"
    except requests.RequestException as err:
        return False, str(err)


def resolve_media_player(options: dict[str, Any]) -> dict[str, Any]:
    configured = str(options.get("media_player") or "").strip()
    entity_id = configured
    if not entity_id or entity_id.lower() in AUTO_SENTINELS:
        players = list_media_players()
        entity_id = players[0]["entity_id"] if players else ""
    if not entity_id:
        return {"ok": False, "error": "未配置或未发现 media_player"}
    state = fetch_state(entity_id)
    attributes = (
        state.get("attributes")
        if state and isinstance(state.get("attributes"), dict)
        else {}
    )
    return {
        "ok": True,
        "entity_id": entity_id,
        "friendly_name": attributes.get("friendly_name") or entity_id,
        "state": (state or {}).get("state") or "unknown",
        "configured": configured,
    }


def test_play() -> dict[str, Any]:
    options = load_options()
    target = resolve_media_player(options)
    if not target.get("ok"):
        return target
    sample = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"
    ok, detail = call_ha_service(
        "media_player",
        "play_media",
        {
            "entity_id": target["entity_id"],
            "media_content_id": sample,
            "media_content_type": "music",
        },
    )
    if not ok:
        return {"ok": False, "error": detail, **target}
    return {
        "ok": True,
        "message": f"已向 {target['entity_id']} 发送测试 play_media",
        "media_content_id": sample,
        **target,
    }


def test_stop() -> dict[str, Any]:
    options = load_options()
    target = resolve_media_player(options)
    if not target.get("ok"):
        return target
    last = "stop failed"
    for service in ("media_stop", "media_pause", "turn_off"):
        ok, detail = call_ha_service(
            "media_player",
            service,
            {"entity_id": target["entity_id"]},
        )
        if ok:
            return {
                "ok": True,
                "message": f"已调用 {service} → {target['entity_id']}",
                **target,
            }
        last = detail
    return {"ok": False, "error": last, **target}


def read_log_tail(limit: int = 20000) -> str:
    for path in LOG_CANDIDATES:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                return handle.read()[-limit:]
        except OSError:
            continue
    return ""


def status() -> dict[str, Any]:
    options = load_options()
    conversation = str(options.get("conversation_entity") or "").strip()
    conv_state = fetch_state(conversation) if conversation else None
    media = resolve_media_player(options)
    return {
        "ok": True,
        "options": options,
        "conversation": {
            "entity_id": conversation or None,
            "state": (conv_state or {}).get("state") if conv_state else None,
            "query": extract_query(conv_state) if conv_state else "",
            "last_updated": (conv_state or {}).get("last_updated") if conv_state else None,
            "missing": bool(conversation) and conv_state is None,
        },
        "media_player": media,
        "players": list_media_players(),
        "conversations": list_conversation_sensors(),
        "cookies": cookies_status(),
    }


def enrich_result(result: dict[str, Any]) -> dict[str, Any]:
    snap = status()
    result["options"] = result.get("options") or snap.get("options")
    result["players"] = snap.get("players")
    result["conversations"] = snap.get("conversations")
    result["conversation"] = snap.get("conversation")
    result["media_player"] = snap.get("media_player")
    result["cookies"] = result.get("cookies") or snap.get("cookies")
    return result


def page_html(*, music_ui_href: str = "../static/default/index.html") -> str:
    """Config page HTML. music_ui_href is relative link to console UI."""
    return HTML_TEMPLATE.replace("__MUSIC_UI_HREF__", music_ui_href)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>XiaoMusic 设置</title>
  <style>
    :root {
      --bg: #12151c;
      --card: #1a1f2b;
      --text: #e8eaed;
      --muted: #9aa0a6;
      --border: #2a3142;
      --accent: #26a69a;
      --danger: #ef5350;
      --ok: #66bb6a;
      --save: #5c6bc0;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--text);
      padding: 20px;
    }
    .card {
      max-width: 720px;
      margin: 0 auto;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px;
    }
    h1 { font-size: 1.25rem; margin: 0 0 6px; }
    h2 { font-size: 1rem; margin: 20px 0 8px; }
    p { color: var(--muted); margin: 0 0 14px; line-height: 1.45; font-size: 0.95rem; }
    a.nav {
      display: inline-block;
      margin: 0 0 14px;
      color: #80cbc4;
      text-decoration: none;
      font-size: 0.95rem;
    }
    a.nav:hover { text-decoration: underline; }
    label { display: block; font-size: 0.88rem; margin: 12px 0 6px; color: var(--muted); }
    select, input[type="text"], input[type="number"], input[type="file"], textarea {
      width: 100%;
      background: #0d0f14;
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 12px;
      font-size: 0.95rem;
    }
    textarea { min-height: 7em; font-family: ui-monospace, Consolas, monospace; font-size: 0.8rem; }
    .check {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 12px;
      color: var(--text);
      font-size: 0.95rem;
    }
    .check input { width: auto; }
    .row { display: flex; gap: 10px; flex-wrap: wrap; margin: 16px 0 8px; }
    button {
      border: 0;
      border-radius: 8px;
      padding: 10px 16px;
      font-size: 0.95rem;
      cursor: pointer;
      color: #fff;
    }
    button:disabled { opacity: 0.45; cursor: not-allowed; }
    .save { background: var(--save); }
    .restart { background: var(--accent); }
    .start { background: #43a047; }
    .stop { background: var(--danger); }
    .meta, .logbox {
      font-family: ui-monospace, Consolas, monospace;
      font-size: 0.8rem;
      background: #0d0f14;
      border-radius: 8px;
      padding: 12px;
      white-space: pre-wrap;
      word-break: break-all;
      border: 1px solid var(--border);
      color: #cfd3da;
    }
    .meta { min-height: 6em; }
    .logbox { min-height: 12em; max-height: 22em; overflow: auto; margin-top: 8px; }
    .ok { color: var(--ok); }
    .err { color: var(--danger); }
    code { color: #80cbc4; }
  </style>
</head>
<body>
  <div class="card">
    <h1>XiaoMusic · 设置</h1>
    <a class="nav" href="__MUSIC_UI_HREF__">← 返回控制台</a>
    <p>选择对话传感器与目标音箱，调整口令与下载选项。保存后建议重启以立即生效。</p>

    <label for="conversation">对话传感器 conversation</label>
    <select id="conversation"></select>

    <label for="player">目标 media_player</label>
    <select id="player"></select>

    <label for="prefixes">口令前缀（逗号分隔）</label>
    <input id="prefixes" type="text" placeholder="播放,播放歌曲,..." />

    <label for="poll">轮询间隔（秒）</label>
    <input id="poll" type="number" min="0.2" step="0.1" />

    <label for="base">音乐公网/局域网基址（可空）</label>
    <input id="base" type="text" placeholder="http://192.168.1.10:8090" />

    <label for="search">yt-dlp 搜索前缀</label>
    <input id="search" type="text" placeholder="bilisearch:" />

    <label class="check"><input id="nodl" type="checkbox" /> 禁用下载（仅本地）</label>
    <label class="check"><input id="verbose" type="checkbox" /> 详细日志</label>

    <h2>yt-dlp Cookies（B 站 412）</h2>
    <p>B 站搜索若报 <code>HTTP 412 Precondition Failed</code>，在浏览器打开一次 <code>bilibili.com</code>，用扩展导出 Netscape 格式 <code>cookies.txt</code>（至少含 <code>buvid3</code>，可不登录），在此上传。</p>
    <label class="check"><input id="cookiesOn" type="checkbox" /> 下载时附带 yt-dlp cookies</label>
    <label for="cookieFile">选择 cookies.txt</label>
    <input id="cookieFile" type="file" accept=".txt,text/plain" />
    <label for="cookieText">或粘贴 cookies 文本</label>
    <textarea id="cookieText" placeholder="# Netscape HTTP Cookie File"></textarea>
    <div class="row">
      <button class="save" id="btnCookie" onclick="uploadCookies()">上传 cookies</button>
    </div>

    <div class="row">
      <button class="save" id="btnSave" onclick="save(false)">保存</button>
      <button class="restart" id="btnRestart" onclick="save(true)">保存并重启</button>
      <button class="start" id="btnTest" onclick="testPlay()">测试播放</button>
      <button class="stop" id="btnStop" onclick="testStop()">停止</button>
    </div>

    <div class="meta" id="status">加载中…</div>

    <h2>插件日志</h2>
    <p>来自 <code>xiaomusic.log.txt</code>（若已生成）。</p>
    <div class="logbox" id="playlog">（尚无日志）</div>
  </div>
  <script>
    let lastPlayers = [];
    let lastConversations = [];

    async function api(path, method, body) {
      const opts = { method: method || 'GET', headers: {} };
      if (body !== undefined) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
      }
      const res = await fetch(path, opts);
      const data = await res.json().catch(() => ({}));
      if (!res.ok && !data.error) data.error = 'HTTP ' + res.status;
      return data;
    }

    function fillSelect(sel, items, current, emptyLabel) {
      const keep = sel.value;
      sel.innerHTML = '';
      const empty = document.createElement('option');
      empty.value = '';
      empty.textContent = emptyLabel;
      sel.appendChild(empty);
      for (const item of items) {
        const opt = document.createElement('option');
        opt.value = item.entity_id;
        const mark = (item.score || 0) >= 100 ? ' ★' : '';
        const preview = item.query_preview ? ' | ' + item.query_preview : '';
        opt.textContent =
          (item.friendly_name || item.entity_id) +
          ' — ' + item.entity_id +
          ' [' + (item.state || '?') + ']' + mark + preview;
        sel.appendChild(opt);
      }
      const prefer = keep || current || '';
      if ([...sel.options].some(o => o.value === prefer)) sel.value = prefer;
      else sel.value = '';
    }

    function applyOptions(opts) {
      opts = opts || {};
      document.getElementById('prefixes').value = opts.command_prefixes || '';
      document.getElementById('poll').value = opts.poll_interval_seconds != null
        ? opts.poll_interval_seconds : 1.0;
      document.getElementById('base').value = opts.music_public_base || '';
      document.getElementById('search').value = opts.search_prefix || 'bilisearch:';
      document.getElementById('nodl').checked = !!opts.disable_download;
      document.getElementById('verbose').checked = !!opts.verbose;
      document.getElementById('cookiesOn').checked = !!opts.enable_yt_dlp_cookies;
    }

    function collectOptions() {
      return {
        conversation_entity: document.getElementById('conversation').value,
        media_player: document.getElementById('player').value,
        command_prefixes: document.getElementById('prefixes').value,
        poll_interval_seconds: Number(document.getElementById('poll').value || 1),
        music_public_base: document.getElementById('base').value,
        search_prefix: document.getElementById('search').value,
        disable_download: document.getElementById('nodl').checked,
        verbose: document.getElementById('verbose').checked,
        enable_yt_dlp_cookies: document.getElementById('cookiesOn').checked,
      };
    }

    function render(data) {
      const opts = data.options || {};
      lastPlayers = data.players || lastPlayers;
      lastConversations = data.conversations || lastConversations;
      fillSelect(
        document.getElementById('conversation'),
        lastConversations,
        opts.conversation_entity || '',
        '请选择 conversation 传感器'
      );
      fillSelect(
        document.getElementById('player'),
        lastPlayers,
        opts.media_player || '',
        '自动识别（推荐）'
      );
      applyOptions(opts);

      const el = document.getElementById('status');
      const lines = [];
      if (data.error) lines.push('错误: ' + data.error);
      if (data.message) lines.push(data.message);
      const conv = data.conversation || {};
      lines.push('对话传感器: ' + (conv.entity_id || '(未设置)'));
      if (conv.missing) lines.push('警告: 实体不存在或不可读');
      if (conv.query) lines.push('最近语句: ' + conv.query);
      if (conv.last_updated) lines.push('对话更新: ' + conv.last_updated);
      const mp = data.media_player || {};
      lines.push('音箱配置: ' + (opts.media_player || '(自动)'));
      lines.push('实际目标: ' + (mp.entity_id || '-'));
      if (mp.friendly_name) lines.push('名称: ' + mp.friendly_name);
      if (mp.state) lines.push('播放器状态: ' + mp.state);
      const ck = data.cookies || {};
      if (ck.present) {
        lines.push(
          'cookies: 已保存 ' + (ck.line_count || 0) + ' 条' +
          (ck.has_bilibili ? ' (含 B 站)' : '') +
          (ck.has_buvid3 ? ' buvid3' : '') +
          (ck.mtime ? ' @ ' + ck.mtime : '')
        );
      } else {
        lines.push('cookies: 未上传');
      }
      lines.push('启用 --cookies: ' + (!!opts.enable_yt_dlp_cookies));
      if (data.restarting) lines.push('插件正在重启…');
      el.textContent = lines.join('\\n');
      el.className = 'meta ' + (data.error || conv.missing || (mp && mp.error) ? 'err' : 'ok');
    }

    async function uploadCookies() {
      document.getElementById('btnCookie').disabled = true;
      try {
        let text = document.getElementById('cookieText').value || '';
        const file = document.getElementById('cookieFile').files[0];
        if (file) text = await file.text();
        const data = await api('./api/cookies', 'POST', {
          text: text,
          enable: true,
        });
        if (data.ok) {
          if (data.options) applyOptions(data.options);
          document.getElementById('cookiesOn').checked = true;
        }
        render(Object.assign(await api('./api/status'), data));
      } finally {
        document.getElementById('btnCookie').disabled = false;
      }
    }

    async function refresh() {
      render(await api('./api/status'));
    }

    async function save(restart) {
      document.getElementById('btnSave').disabled = true;
      document.getElementById('btnRestart').disabled = true;
      try {
        const data = await api('./api/options', 'POST', {
          options: collectOptions(),
          restart: !!restart,
        });
        render(data);
      } finally {
        document.getElementById('btnSave').disabled = false;
        document.getElementById('btnRestart').disabled = false;
      }
    }

    async function testPlay() {
      document.getElementById('btnTest').disabled = true;
      try {
        const data = await api('./api/test/play', 'POST', collectOptions());
        render(Object.assign(await api('./api/status'), data));
      } finally {
        document.getElementById('btnTest').disabled = false;
      }
    }

    async function testStop() {
      document.getElementById('btnStop').disabled = true;
      try {
        const data = await api('./api/test/stop', 'POST');
        render(Object.assign(await api('./api/status'), data));
      } finally {
        document.getElementById('btnStop').disabled = false;
      }
    }

    async function refreshLog() {
      const data = await api('./api/log');
      const el = document.getElementById('playlog');
      const text = (data.text || '').trim();
      const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 24;
      el.textContent = text || '（尚无日志）';
      if (atBottom) el.scrollTop = el.scrollHeight;
    }

    refresh();
    refreshLog();
    setInterval(refresh, 5000);
    setInterval(refreshLog, 2000);
  </script>
</body>
</html>
"""
