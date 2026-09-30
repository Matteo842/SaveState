"""Parse launcher URLs before recognizing their protocol or Steam store host."""

import re
from urllib.parse import SplitResult, urlsplit


_LAUNCHER_SCHEMES = frozenset({
    "steam", "com.epicgames.launcher", "uplay", "goggalaxy", "battlenet", "origin",
})


def _parse_launcher_url(value: str) -> SplitResult | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or "\\" in value or any(char.isspace() or ord(char) < 32 for char in value):
        return None
    try:
        parsed = urlsplit(value)
        # Credentials and malformed ports have no place in launcher shortcuts.
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return None
        port = parsed.port
        if parsed.scheme in _LAUNCHER_SCHEMES and port is not None:
            return None
        return parsed
    except ValueError:
        return None


def is_steam_url(value: str) -> bool:
    """Recognize a Steam protocol URL or an HTTP(S) URL on the exact store host."""
    parsed = _parse_launcher_url(value)
    return parsed is not None and (
        parsed.scheme == "steam"
        or (
            parsed.scheme in {"http", "https"}
            and parsed.hostname == "store.steampowered.com"
        )
    )


def is_known_launcher_url(value: str) -> bool:
    """Recognize supported native launcher schemes and Steam store links."""
    parsed = _parse_launcher_url(value)
    return parsed is not None and (
        parsed.scheme in _LAUNCHER_SCHEMES or is_steam_url(value)
    )


def get_steam_app_id(value: str) -> str | None:
    """Extract an AppID only from a validated rungameid or Steam store app URL."""
    parsed = _parse_launcher_url(value)
    if parsed is None:
        return None
    if parsed.scheme == "steam" and parsed.hostname == "rungameid":
        match = re.fullmatch(r"/([0-9]+)(?:/.*)?", parsed.path)
    elif (
        parsed.scheme in {"http", "https"}
        and parsed.hostname == "store.steampowered.com"
    ):
        match = re.fullmatch(r"/app/([0-9]+)(?:/.*)?", parsed.path)
    else:
        return None
    return match.group(1) if match else None
