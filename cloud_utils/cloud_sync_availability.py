"""
cloud_sync_availability.py

Central checks for whether per-profile "Sync backups online" can be enabled
or is currently operational.

We are deliberately strict: the user must never believe a save was synced
when it was not. Enabling online sync requires provider configuration,
network reachability, and an active connection.
"""

from __future__ import annotations

import logging
import socket
from typing import Any, Tuple

# (available, user-facing reason when unavailable)
Availability = Tuple[bool, str]


def _has_network(timeout: float = 2.0) -> bool:
    """Best-effort check that the machine can reach the internet."""
    for host, port in (("8.8.8.8", 53), ("1.1.1.1", 53)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def is_provider_configured(
    provider_type: str,
    cloud_settings: dict | None,
    drive_manager: Any = None,
) -> Availability:
    """Return whether the active provider has the minimum setup to connect."""
    settings = cloud_settings if isinstance(cloud_settings, dict) else {}
    provider_type = (provider_type or "google_drive").strip().lower()

    if provider_type == "google_drive":
        if drive_manager is None:
            return False, "Google Drive is not available"
        try:
            if not drive_manager.client_secret_file.exists():
                return False, "Google Drive is not set up (connect once in the Cloud panel)"
        except Exception:
            return False, "Google Drive is not set up"
        return True, ""

    if provider_type == "smb":
        if not (settings.get("smb_path") or "").strip():
            return False, "SMB/network folder is not configured (Cloud panel → Configure)"
        return True, ""

    if provider_type == "ftp":
        if not (settings.get("ftp_host") or "").strip():
            return False, "FTP server is not configured (Cloud panel → Configure)"
        return True, ""

    if provider_type == "webdav":
        if not (settings.get("webdav_url") or "").strip():
            return False, "WebDAV server is not configured (Cloud panel → Configure)"
        return True, ""

    if provider_type == "git":
        repo = (settings.get("git_repo_path") or "").strip()
        remote = (settings.get("git_remote_url") or "").strip()
        if not repo and not remote:
            return False, "Git repository is not configured (Cloud panel → Configure)"
        return True, ""

    return False, f"Unknown cloud provider '{provider_type}'"


def evaluate_online_sync_availability(
    *,
    provider_type: str,
    cloud_settings: dict | None,
    provider: Any,
    drive_manager: Any = None,
    require_connection: bool = True,
    check_network: bool = True,
) -> Availability:
    """Full gate used by the UI and auto-upload paths.

    Parameters
    ----------
    require_connection:
        When True (default), a live provider connection is mandatory.
    check_network:
        When True (default), a basic internet reachability probe runs first.
    """
    configured, reason = is_provider_configured(
        provider_type, cloud_settings, drive_manager=drive_manager,
    )
    if not configured:
        return False, reason

    if check_network and not _has_network():
        return False, "no internet connection detected"

    if provider is None:
        return False, "no cloud provider is available"

    if require_connection and not getattr(provider, "is_connected", False):
        label = provider_type.replace("_", " ").title()
        return False, f"{label} is not connected (open the Cloud panel and connect)"

    return True, ""


def profile_wants_online_sync(profile_data: dict | None) -> bool:
    """True if this profile has automatic online sync enabled in its config."""
    if not isinstance(profile_data, dict):
        return False
    ab = profile_data.get("auto_backup")
    if not isinstance(ab, dict):
        return False
    return bool(ab.get("enabled")) and bool(ab.get("sync_online"))
