"""路由注册"""

from xiaomusic.api import websocket
from xiaomusic.api.routers import (
    device,
    file,
    ha_config,
    music,
    playlist,
    plugin,
    system,
)


def register_routers(app):
    """注册所有路由到应用

    Args:
        app: FastAPI 应用实例
    """
    # 注册各个路由模块
    app.include_router(system.router, tags=["系统管理"])
    app.include_router(device.router, tags=["设备控制"])
    app.include_router(music.router, tags=["音乐管理"])
    app.include_router(playlist.router, tags=["播放列表"])
    app.include_router(plugin.router, tags=["插件管理"])
    app.include_router(file.router, tags=["文件操作"])
    app.include_router(websocket.router, tags=["WebSocket"])
    # HA add-on options UI (no basic-auth dependency).
    app.include_router(ha_config.router)
