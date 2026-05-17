"""YouTube / YouTube Shorts URL → embed video id."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

_YT_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
        "www.youtu.be",
    }
)


def _parse_youtube_url(url: str | None) -> tuple[str | None, bool]:
    """Return (video_id, is_shorts)."""
    raw = (url or "").strip()
    if not raw:
        return None, False
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except Exception:
        return None, False
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if host not in {h.removeprefix("www.") for h in _YT_HOSTS} and host not in _YT_HOSTS:
        if "youtube" not in host and "youtu.be" not in host:
            return None, False
    path = parsed.path or ""
    is_shorts = bool(re.search(r"/shorts/", path, re.I)) or bool(
        re.search(r"youtube\.com/shorts/", raw, re.I)
    )
    if host.endswith("youtu.be") or host == "youtu.be":
        vid = path.strip("/").split("/")[0]
        return (vid if _valid_id(vid) else None), False
    shorts = re.match(r"^/shorts/([A-Za-z0-9_-]{11})", path)
    if shorts:
        return shorts.group(1), True
    embed = re.match(r"^/embed/([A-Za-z0-9_-]{11})", path)
    if embed:
        return embed.group(1), is_shorts
    if path.strip("/") == "watch":
        q = parse_qs(parsed.query).get("v", [None])[0]
        return (q if q and _valid_id(q) else None), False
    live = re.match(r"^/live/([A-Za-z0-9_-]{11})", path)
    if live:
        return live.group(1), False
    return None, False


def youtube_video_id(url: str | None) -> str | None:
    vid, _ = _parse_youtube_url(url)
    return vid


def youtube_embed_info(url: str | None) -> dict[str, str] | None:
    """{'id': video_id, 'layout': 'shorts'|'standard'} for home guide embed."""
    vid, is_shorts = _parse_youtube_url(url)
    if not vid:
        return None
    return {"id": vid, "layout": "shorts" if is_shorts else "standard"}


def _valid_id(vid: str) -> bool:
    return bool(vid) and len(vid) <= 32 and re.fullmatch(r"[A-Za-z0-9_-]+", vid) is not None
