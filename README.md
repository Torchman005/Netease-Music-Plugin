# NetEase Music Plugin

Yuyu-Mind can control NetEase Cloud Music through a local `api-enhanced` service:

[neteasecloudmusicapienhanced/api-enhanced](https://github.com/neteasecloudmusicapienhanced/api-enhanced)

```text
agent/plugins/netease_music/
  plugin.json
  config.json
  main.py
```

## What It Does

- Search songs on NetEase Cloud Music.
- Resolve a song playback URL through `/song/url/v1`.
- Optionally open the playback URL with the OS default handler.
- Fetch lyrics.
- Keep a lightweight plugin playback state for status, pause, stop, and resume.

The NetEase API returns music data and URLs. It does not directly control the official NetEase desktop app. If `openPlaybackUrl` opens the URL in a browser or media player, pause/stop commands can only update plugin state unless that external player exposes its own control API.

## Start API Enhanced

Clone and start the API service separately:

```powershell
git clone https://github.com/neteasecloudmusicapienhanced/api-enhanced.git
cd api-enhanced
npm install
node app.js
```

The plugin defaults to:

```text
http://127.0.0.1:3000
```

## Configure

Edit `agent/plugins/netease_music/config.json`:

```json
{
  "apiBaseUrl": "http://127.0.0.1:3000",
  "timeoutSeconds": 12,
  "proxy": "",
  "cookie": "",
  "defaultLimit": 5,
  "defaultQuality": "exhigh",
  "openPlaybackUrl": true
}
```

Environment variable alternatives:

```env
YUYU_NETEASE_API_BASE_URL=http://127.0.0.1:3000
YUYU_NETEASE_COOKIE=your_netease_cookie
YUYU_NETEASE_QUALITY=exhigh
YUYU_NETEASE_OPEN_PLAYBACK_URL=true
```

Some songs or high-quality URLs may require login cookies or membership permissions.

## Conversation Triggers

Examples:

```text
播放 晴天
网易云搜一下 星茶会
找一下 周杰伦 稻香
这首歌的歌词
暂停音乐
继续播放
现在放的什么
```

## API

List plugins:

```http
GET http://127.0.0.1:8765/plugins
```

Control music:

```http
POST http://127.0.0.1:8765/plugins/netease_music/control
Content-Type: application/json

{"message":"播放 晴天"}
```

Explicit intent:

```json
{"intent":"search","query":"星茶会","limit":5}
```

Response shape:

```json
{
  "ok": true,
  "plugin": "netease_music",
  "action": "control",
  "summary": "准备播放：晴天 - 周杰伦。",
  "metadata": {
    "intent": "play",
    "song": {
      "id": 186016,
      "name": "晴天",
      "artists": "周杰伦"
    },
    "playbackUrl": "https://..."
  }
}
```
