from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any


PLUGIN_DIR = Path(__file__).resolve().parent
STATE_PATH = PLUGIN_DIR / "state.json"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _config(payload: dict[str, Any]) -> dict[str, Any]:
    config = payload.get("config", {})
    return config if isinstance(config, dict) else {}


def _config_string(config: dict[str, Any], key: str, env_name: str, default: str = "") -> str:
    value = str(config.get(key, "")).strip()
    return value or _env(env_name, default)


def _config_int(config: dict[str, Any], key: str, env_name: str, default: int) -> int:
    value = config.get(key)
    if value not in (None, ""):
        return int(value)
    return int(_env(env_name, str(default)) or str(default))


def _config_bool(config: dict[str, Any], key: str, env_name: str, default: bool) -> bool:
    value = config.get(key)
    if isinstance(value, bool):
        return value
    if value not in (None, ""):
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    return _env(env_name, str(default).lower()).lower() in {"1", "true", "yes", "on"}


def _api_base(config: dict[str, Any]) -> str:
    return _config_string(config, "apiBaseUrl", "YUYU_NETEASE_API_BASE_URL", "http://127.0.0.1:3000").rstrip("/")


def _cookie(config: dict[str, Any]) -> str:
    return _config_string(config, "cookie", "YUYU_NETEASE_COOKIE") or _env("NETEASE_COOKIE")


def _proxy(config: dict[str, Any]) -> str:
    return _config_string(config, "proxy", "YUYU_NETEASE_PROXY") or _env("HTTPS_PROXY") or _env("HTTP_PROXY")


def _opener(config: dict[str, Any]) -> urllib.request.OpenerDirector:
    proxy = _proxy(config)
    if proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener()


def _api_get(config: dict[str, Any], path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    timeout_seconds = max(3, min(60, _config_int(config, "timeoutSeconds", "YUYU_NETEASE_TIMEOUT_SECONDS", 12)))
    query = dict(params or {})
    cookie = _cookie(config)
    if cookie and "cookie" not in query:
        query["cookie"] = cookie
    url = f"{_api_base(config)}{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query, doseq=True)
    request = urllib.request.Request(url, headers={"User-Agent": "Yuyu-Mind/0.1 netease_music plugin"})
    try:
        with _opener(config).open(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"NetEase API error {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"NetEase API is not reachable at {_api_base(config)}. "
            "Start api-enhanced first, then retry. "
            f"Detail: {error}"
        ) from error


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _extract_query(message: str) -> str:
    text = _clean_text(message)
    text = re.sub(
        r"^(帮我|请|麻烦|yuyu)?\s*(在)?(网易云音乐|网易云)?\s*(播放|放一首|放|听|搜歌|找歌|搜索|搜一下|查一下|歌词)\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"(的)?歌词$", "", text).strip(" ：:，,。.!?！？")
    return text or _clean_text(message)


def _infer_intent(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("intent", "")).strip().lower()
    if explicit:
        return explicit
    message = str(payload.get("message") or payload.get("query") or payload.get("prompt") or "").lower()
    if any(token in message for token in ["暂停", "停一下", "pause"]):
        return "pause"
    if any(token in message for token in ["停止", "关掉音乐", "stop"]):
        return "stop"
    if any(token in message for token in ["继续", "恢复", "resume"]):
        return "resume"
    if any(token in message for token in ["歌词", "lyric"]):
        return "lyric"
    if any(token in message for token in ["状态", "现在放", "status"]):
        return "status"
    if any(token in message for token in ["播放", "放一首", "听", "play"]):
        return "play"
    return "search"


def _song_artists(song: dict[str, Any]) -> str:
    artists = song.get("artists") or song.get("ar") or []
    if not isinstance(artists, list):
        return ""
    names = [str(item.get("name", "")).strip() for item in artists if isinstance(item, dict) and str(item.get("name", "")).strip()]
    return " / ".join(names)


def _normalize_song(song: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": song.get("id"),
        "name": song.get("name", ""),
        "artists": _song_artists(song),
        "album": ((song.get("album") or song.get("al") or {}) if isinstance(song.get("album") or song.get("al") or {}, dict) else {}).get("name", ""),
        "durationMs": song.get("duration") or song.get("dt"),
    }


def _search_songs(config: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
    data = _api_get(config, "/search", {"keywords": query, "type": 1, "limit": limit})
    songs = data.get("result", {}).get("songs", [])
    if not isinstance(songs, list):
        return []
    return [_normalize_song(song) for song in songs if isinstance(song, dict)]


def _song_detail(config: dict[str, Any], song_id: int) -> dict[str, Any]:
    data = _api_get(config, "/song/detail", {"ids": song_id})
    songs = data.get("songs", [])
    if isinstance(songs, list) and songs:
        return _normalize_song(songs[0])
    return {"id": song_id}


def _song_url(config: dict[str, Any], song_id: int) -> dict[str, Any]:
    quality = _config_string(config, "defaultQuality", "YUYU_NETEASE_QUALITY", "exhigh")
    data = _api_get(config, "/song/url/v1", {"id": song_id, "level": quality})
    items = data.get("data", [])
    if not isinstance(items, list) or not items:
        return {}
    item = items[0] if isinstance(items[0], dict) else {}
    return {
        "url": item.get("url"),
        "level": item.get("level") or quality,
        "type": item.get("type"),
        "size": item.get("size"),
        "br": item.get("br"),
        "code": item.get("code"),
    }


def _format_song(song: dict[str, Any]) -> str:
    name = str(song.get("name", "")).strip() or f"ID {song.get('id')}"
    artists = str(song.get("artists", "")).strip()
    return f"{name} - {artists}" if artists else name


def _search(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    query = _extract_query(str(payload.get("query") or payload.get("message") or payload.get("prompt") or ""))
    limit = max(1, min(20, int(payload.get("limit") or _config_int(config, "defaultLimit", "YUYU_NETEASE_DEFAULT_LIMIT", 5))))
    songs = _search_songs(config, query, limit)
    if not songs:
        return {"ok": False, "plugin": "netease_music", "action": "control", "error": f"没有搜到：{query}", "summary": ""}
    lines = [f"网易云搜索「{query}」结果："]
    for index, song in enumerate(songs, start=1):
        lines.append(f"{index}. {_format_song(song)} (id: {song.get('id')})")
    return {
        "ok": True,
        "plugin": "netease_music",
        "action": "control",
        "summary": "\n".join(lines),
        "metadata": {"intent": "search", "query": query, "songs": songs},
    }


def _play(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    raw_song_id = payload.get("songId") or payload.get("id")
    song_id = int(raw_song_id) if raw_song_id not in (None, "") else 0
    query = _extract_query(str(payload.get("query") or payload.get("message") or payload.get("prompt") or ""))
    song = {}
    if song_id:
        song = _song_detail(config, song_id)
    else:
        songs = _search_songs(config, query, 1)
        if not songs:
            return {"ok": False, "plugin": "netease_music", "action": "control", "error": f"没有搜到可以播放的歌曲：{query}", "summary": ""}
        song = songs[0]
        song_id = int(song.get("id") or 0)

    url_info = _song_url(config, song_id)
    playback_url = str(url_info.get("url") or "").strip()
    if not playback_url:
        return {
            "ok": False,
            "plugin": "netease_music",
            "action": "control",
            "error": f"没有拿到播放链接：{_format_song(song)}。可能需要登录 cookie、会员权限或更换音质。",
            "summary": "",
            "metadata": {"intent": "play", "song": song, "urlInfo": url_info},
        }

    opened = False
    if _config_bool(config, "openPlaybackUrl", "YUYU_NETEASE_OPEN_PLAYBACK_URL", True):
        opened = webbrowser.open(playback_url)
    state = {"isPlaying": True, "song": song, "playbackUrl": playback_url, "urlInfo": url_info}
    _save_state(state)
    opened_text = "已尝试用默认播放器打开播放链接。" if opened else "已拿到播放链接，但系统没有确认打开。"
    return {
        "ok": True,
        "plugin": "netease_music",
        "action": "control",
        "summary": f"准备播放：{_format_song(song)}。\n{opened_text}",
        "metadata": {"intent": "play", "song": song, "playbackUrl": playback_url, "urlInfo": url_info, "opened": opened},
    }


def _lyric(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    raw_song_id = payload.get("songId") or payload.get("id")
    song_id = int(raw_song_id) if raw_song_id not in (None, "") else 0
    query = _extract_query(str(payload.get("query") or payload.get("message") or payload.get("prompt") or ""))
    song = {}
    if not song_id:
        songs = _search_songs(config, query, 1)
        if not songs:
            return {"ok": False, "plugin": "netease_music", "action": "control", "error": f"没有搜到歌词对应歌曲：{query}", "summary": ""}
        song = songs[0]
        song_id = int(song.get("id") or 0)
    else:
        song = _song_detail(config, song_id)
    data = _api_get(config, "/lyric", {"id": song_id})
    lyric = str((data.get("lrc") or {}).get("lyric") or "").strip()
    translated = str((data.get("tlyric") or {}).get("lyric") or "").strip()
    preview = "\n".join([line for line in lyric.splitlines() if line.strip()][:12])
    if not preview:
        preview = "没有拿到歌词。"
    return {
        "ok": True,
        "plugin": "netease_music",
        "action": "control",
        "summary": f"{_format_song(song)} 的歌词片段：\n{preview}",
        "metadata": {"intent": "lyric", "song": song, "lyric": lyric, "translatedLyric": translated},
    }


def _status(config: dict[str, Any]) -> dict[str, Any]:
    state = _load_state()
    login = {}
    try:
        login = _api_get(config, "/login/status")
    except Exception as error:
        login = {"error": str(error)}
    if state.get("song"):
        summary = f"当前插件记录：{'播放中' if state.get('isPlaying') else '未播放'}，{_format_song(state['song'])}。"
    else:
        summary = "当前插件还没有播放记录。"
    return {
        "ok": True,
        "plugin": "netease_music",
        "action": "control",
        "summary": summary,
        "metadata": {"intent": "status", "state": state, "login": login},
    }


def _state_action(intent: str) -> dict[str, Any]:
    state = _load_state()
    if intent in {"pause", "stop"}:
        state["isPlaying"] = False
        _save_state(state)
        action_text = "暂停" if intent == "pause" else "停止"
        return {
            "ok": True,
            "plugin": "netease_music",
            "action": "control",
            "summary": f"已将插件播放状态标记为{action_text}。如果歌曲是在外部浏览器或播放器里打开的，还需要在那个播放器里暂停。",
            "metadata": {"intent": intent, "state": state, "limitedControl": True},
        }
    if intent == "resume":
        state["isPlaying"] = True
        _save_state(state)
        playback_url = str(state.get("playbackUrl", "")).strip()
        opened = webbrowser.open(playback_url) if playback_url else False
        return {
            "ok": True,
            "plugin": "netease_music",
            "action": "control",
            "summary": "已尝试继续播放上一首。" if opened else "没有可继续播放的链接，先让我播放一首歌吧。",
            "metadata": {"intent": intent, "state": state, "opened": opened},
        }
    raise RuntimeError(f"unsupported state intent: {intent}")


def control(payload: dict[str, Any]) -> dict[str, Any]:
    config = _config(payload)
    intent = _infer_intent(payload)
    if intent == "search":
        return _search(payload, config)
    if intent == "play":
        return _play(payload, config)
    if intent == "lyric":
        return _lyric(payload, config)
    if intent == "status":
        return _status(config)
    if intent in {"pause", "stop", "resume"}:
        return _state_action(intent)
    return {"ok": False, "plugin": "netease_music", "action": "control", "error": f"未知音乐指令：{intent}", "summary": ""}


ACTIONS = {"control": control}
