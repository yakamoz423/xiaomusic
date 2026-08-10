# XiaoMusic (Home Assistant add-on)

Voice commands on a Xiaomi XiaoAI speaker → MIOT conversation sensor → this
add-on → yt-dlp download → `media_player.play_media` over a LAN HTTP URL.

No Xiaomi account / MiNA login is required in add-on mode.

## Pipeline

```text
XiaoAI voice
  → hass_xiaomi_miot conversation sensor
  → XiaoMusic add-on (prefix match + yt-dlp)
  → HTTP file server (host network)
  → media_player.play_media → XiaoAI speaker
```

## Install

1. **Settings → Add-ons → Add-on store → ⋮ → Repositories**
2. Add `https://github.com/yakamoz423/xiaomusic`
3. Refresh, install **XiaoMusic**
4. Start the add-on, open **Ingress** for the music UI; open `/ha-config`
   to pick conversation sensor + media player, then **Save and restart**

Add-on folder: top-level `ha_xiaomusic/`.  
Images: `ghcr.io/yakamoz423/{arch}-xiaomusic`.

## Web UI

- **Ingress / 侧栏** → 原版 XiaoMusic 音乐管理界面（端口 `8090`）
- **HA 设备配置** → 同一端口下的 `/ha-config`（或可选独立端口 `8099`）
- 音箱取音乐仍走主机 `8090` 的 HTTP 文件服务

## Configuration

| Option | Required | Notes |
|--------|----------|--------|
| `conversation_entity` | yes | e.g. `sensor.xiaomi_l05c_xxxx_conversation` |
| `media_player` | no | Empty = auto-pick (prefers XiaoAI / Xiaomi) |
| `command_prefixes` | no | Default play keywords |
| `poll_interval_seconds` | no | Default `1.0`; also calls `update_entity` |
| `music_public_base` | no | Empty = UDP-detected LAN IP + port `8090` |
| `disable_download` | no | Local / already-downloaded only |
| `search_prefix` | no | Default `bilisearch:` |
| `verbose` | no | Debug logs |

Same options are editable in **Configuration** tab or `/ha-config`.

Permissions: `hassio_api`, `homeassistant_api`, `host_network`, `media:rw`, `addon_config:rw`.

## Acceptance checks

1. Say 「播放歌曲xxx」 → add-on log shows match + yt-dlp.
2. After download, `play_media` points at `http://<lan-ip>:8090/music/...` and audio plays.
3. 「下一首 / 停止」 work through the HA backend.
4. Add-on options do **not** ask for Xiaomi account/password.

## Notes

- Music files go under `/media/xiaomusic` when the media share is mapped.
- Ingress opens the original music UI on `8090`; HA device settings are at `/ha-config`.
