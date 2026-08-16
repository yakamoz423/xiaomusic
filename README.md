# XiaoMusic (HAOS fork)

小爱音箱语音口令 → MIOT conversation 传感器 → yt-dlp → `media_player.play_media`。  
**插件模式无需小米账号。**

基于 [hanxi/xiaomusic](https://github.com/hanxi/xiaomusic) 的精简 fork。

## 安装

1. **设置 → 插件 → 插件商店 → ⋮ → 仓库**
2. 添加：`https://github.com/yakamoz423/xiaomusic`
3. 安装 **XiaoMusic**，打开 Ingress 选择对话传感器与音箱后「保存并重启」

B 站搜索若报 HTTP 412：在 Ingress **设置** 页上传 Netscape 格式 `cookies.txt`（浏览器打开一次 bilibili.com 后导出，建议含 `buvid3`）。

镜像：`ghcr.io/yakamoz423/{arch}-xiaomusic`  
说明：[`ha_xiaomusic/DOCS.md`](ha_xiaomusic/DOCS.md)
