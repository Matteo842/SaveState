# steam_cloud_utils.py
# -*- coding: utf-8 -*-
"""
Detect whether Steam games support Steam Cloud saves.

Uses the public Steam Store API (category 23 = "Steam Cloud") with a local
JSON cache to avoid repeated network requests.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

try:
    import requests
except ImportError:
    requests = None

STEAM_CLOUD_CATEGORY_ID = 23
STORE_API_URL = "https://store.steampowered.com/api/appdetails"
CACHE_FILENAME = "steam_cloud_cache.json"
REQUEST_DELAY_SEC = 0.5
REQUEST_TIMEOUT_SEC = 15

_cloud_cache: Optional[Dict[str, dict]] = None


def _get_cache_path() -> Optional[str]:
    try:
        from core import settings_manager as _sm
        config_dir = _sm.get_active_config_dir()
    except Exception:
        import config
        config_dir = config.get_app_data_folder()

    if not config_dir:
        return None
    try:
        os.makedirs(config_dir, exist_ok=True)
    except OSError:
        return None
    return os.path.join(config_dir, CACHE_FILENAME)


def _load_cache() -> Dict[str, dict]:
    global _cloud_cache
    if _cloud_cache is not None:
        return _cloud_cache

    _cloud_cache = {}
    cache_path = _get_cache_path()
    if not cache_path or not os.path.isfile(cache_path):
        return _cloud_cache

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _cloud_cache = data
    except Exception as e:
        logging.warning(f"Unable to read Steam cloud cache '{cache_path}': {e}")
        _cloud_cache = {}

    return _cloud_cache


def _save_cache() -> None:
    cache_path = _get_cache_path()
    if not cache_path or _cloud_cache is None:
        return
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(_cloud_cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.warning(f"Unable to save Steam cloud cache '{cache_path}': {e}")


def clear_cloud_cache() -> None:
    """Clear the in-memory cloud status cache."""
    global _cloud_cache
    _cloud_cache = None


def _cache_entry(has_cloud: Optional[bool], source: str) -> dict:
    return {
        "has_cloud_saves": has_cloud,
        "source": source,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _query_store_api(appid: str) -> Optional[bool]:
    """Return True/False for cloud support, or None if the query failed."""
    if requests is None:
        logging.error("Library 'requests' not available; cannot query Steam Store API.")
        return None

    try:
        response = requests.get(
            STORE_API_URL,
            params={"appids": appid, "filters": "categories"},
            timeout=REQUEST_TIMEOUT_SEC,
        )
        if response.status_code == 429:
            logging.warning(f"Steam Store API rate limit hit while checking AppID {appid}.")
            return None

        response.raise_for_status()
        payload = response.json()
    except Exception as e:
        logging.warning(f"Steam Store API request failed for AppID {appid}: {e}")
        return None

    app_data = payload.get(str(appid), {})
    if not app_data.get("success"):
        logging.debug(f"Steam Store API returned no data for AppID {appid}.")
        return None

    categories = app_data.get("data", {}).get("categories", [])
    return any(cat.get("id") == STEAM_CLOUD_CATEGORY_ID for cat in categories)


def get_cached_cloud_status(appid: str) -> Optional[bool]:
    """Return cached cloud status without triggering network requests."""
    cache = _load_cache()
    entry = cache.get(str(appid))
    if isinstance(entry, dict) and "has_cloud_saves" in entry:
        return entry["has_cloud_saves"]
    return None


def get_cloud_save_status(appid: str, force_refresh: bool = False) -> Optional[bool]:
    """
    Check whether a Steam game supports cloud saves.

    Returns:
        True  - game has Steam Cloud (category 23)
        False - game does not have Steam Cloud
        None  - status unknown (API failure, delisted game, etc.)
    """
    appid = str(appid)
    cache = _load_cache()

    if not force_refresh and appid in cache:
        cached = cache[appid]
        if isinstance(cached, dict) and "has_cloud_saves" in cached:
            return cached["has_cloud_saves"]

    has_cloud = _query_store_api(appid)
    cache[appid] = _cache_entry(has_cloud, "store_api")
    _save_cache()
    return has_cloud


def get_cloud_save_status_batch(
    appids: List[str],
    force_refresh: bool = False,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> Dict[str, Optional[bool]]:
    """
    Resolve cloud-save status for multiple AppIDs.

    Uses the local cache first, then queries the Store API only for missing entries.
    """
    appids = [str(a) for a in appids]
    cache = _load_cache()
    results: Dict[str, Optional[bool]] = {}
    to_fetch: List[str] = []

    for appid in appids:
        if not force_refresh and appid in cache:
            cached = cache[appid]
            if isinstance(cached, dict) and "has_cloud_saves" in cached:
                results[appid] = cached["has_cloud_saves"]
                continue
        to_fetch.append(appid)

    total = len(to_fetch)
    for index, appid in enumerate(to_fetch, start=1):
        if progress_callback:
            progress_callback(appid, index, total)

        has_cloud = _query_store_api(appid)
        results[appid] = has_cloud
        cache[appid] = _cache_entry(has_cloud, "store_api")
        _save_cache()

        if index < total:
            time.sleep(REQUEST_DELAY_SEC)

    return results


def format_cloud_status(has_cloud: Optional[bool]) -> str:
    """Return a short user-facing label for the cloud status."""
    if has_cloud is True:
        return "Yes"
    if has_cloud is False:
        return "No"
    return "?"
