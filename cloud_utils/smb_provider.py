# cloud_utils/smb_provider.py
# -*- coding: utf-8 -*-
"""
SMB/Network Folder Provider - Handles backup sync to network shares and local folders.

This provider works with:
- Windows UNC paths (\\\\server\\share)
- Mapped network drives (Z:\\backups)
- Local folders (for testing)
- Linux/macOS mounted shares (/mnt/nas/backups)
- smb:// URIs on both platforms

On Linux the provider resolves SMB URIs (smb://...) and UNC-style paths
(\\\\server\\share) to their GVFS mount point at
``/run/user/<UID>/gvfs/smb-share:server=<srv>,share=<share>``.  If the share
is not already mounted, it will try to mount it via ``gio mount``, feeding
any supplied credentials on stdin.

No third-party Python dependencies required - the provider uses only the
standard library plus the ``gio`` binary on Linux.
"""

import os
import re
import sys
import shutil
import logging
import hashlib
import posixpath
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

from cloud_utils.storage_provider import StorageProvider, ProviderType


# ---------------------------------------------------------------------------
# Path parsing helpers
# ---------------------------------------------------------------------------

# Matches smb://[user[:pass]@]server[:port]/share/subpath
_SMB_URI_RE = re.compile(
    r'^smb://(?:[^/@]+@)?([^/:]+)(?::\d+)?/([^/]+)(?:/(.*))?$',
    re.IGNORECASE,
)

# Matches \\server\share\subpath or //server/share/subpath (after backslash→slash)
_UNC_RE = re.compile(r'^//([^/]+)/([^/]+)(?:/(.*))?$')


def _parse_share_path(raw_path: str) -> Optional[Dict[str, str]]:
    """Parse an SMB/UNC path into its components.

    Returns a dict with keys 'server', 'share', 'subpath' (may be empty string),
    or None if the path is not a recognizable SMB/UNC path (e.g. local path,
    mapped drive).
    """
    if not raw_path:
        return None

    path = raw_path.strip()

    # smb://server/share/subpath
    m = _SMB_URI_RE.match(path)
    if m:
        server, share, subpath = m.group(1), m.group(2), m.group(3) or ''
        return {
            'server': server,
            'share': share,
            'subpath': subpath.strip('/').strip('\\'),
        }

    # \\server\share\subpath  OR  //server/share/subpath
    # Only treat as UNC if the path clearly starts with a double
    # separator (\\ or //) — we must NOT rewrite normal Linux paths like
    # "/mnt/nas/backups" into UNC form.
    is_unc_like = path.startswith('\\\\') or path.startswith('//')
    if is_unc_like:
        normalized = path.replace('\\', '/')
        # Collapse any extra leading slashes down to exactly two
        normalized = '//' + normalized.lstrip('/')
        m = _UNC_RE.match(normalized)
        if m:
            server, share, subpath = m.group(1), m.group(2), m.group(3) or ''
            return {
                'server': server,
                'share': share,
                'subpath': subpath.strip('/'),
            }

    return None


def _to_windows_unc(info: Dict[str, str]) -> str:
    """Build a Windows-style UNC path from parsed components."""
    base = f"\\\\{info['server']}\\{info['share']}"
    if info.get('subpath'):
        base += '\\' + info['subpath'].replace('/', '\\')
    return base


class SMBProvider(StorageProvider):
    """
    Storage provider for network folders (SMB/CIFS shares).
    
    This is the simplest provider as it uses standard filesystem operations.
    Works with any path accessible to the OS:
    - Windows: \\\\server\\share\\folder or Z:\\folder
    - Linux/macOS: /mnt/nas/folder
    """
    
    # Folder name where SaveState stores backups on the network share
    APP_FOLDER_NAME = "SaveState Backups"
    
    def __init__(self):
        """Initialize the SMB provider."""
        super().__init__()
        
        # Configuration
        self._base_path: Optional[str] = None  # Raw user-entered path (e.g. smb://... or \\server\share)
        self._resolved_base_path: Optional[str] = None  # Platform-resolved local path (e.g. GVFS mount)
        self._app_folder_path: Optional[str] = None  # Full path to SaveState folder
        
        # Connection state
        self._connected = False
        
        # Optional credentials
        self._use_credentials = False
        self._username: Optional[str] = None
        self._domain: Optional[str] = None
        # Password kept only in memory for current session (never persisted)
        self._password: Optional[str] = None
    
    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.SMB
    
    @property
    def name(self) -> str:
        return "Network Folder"
    
    @property
    def icon_name(self) -> str:
        return "network_folder.png"
    
    @property
    def is_connected(self) -> bool:
        """Check if connected (path is accessible)."""
        if not self._connected or not self._app_folder_path:
            return False
        
        # Verify the path is still accessible
        try:
            return os.path.isdir(self._app_folder_path)
        except (OSError, PermissionError):
            return False
    
    @property
    def base_path(self) -> Optional[str]:
        """Get the configured base network path (as user entered it)."""
        return self._base_path

    def set_password(self, password: Optional[str]) -> None:
        """Set the in-memory password used for credentialed SMB connections.

        The password is NEVER written to disk. It lives only for the current
        process session so that auto-connect can succeed without re-prompting.
        """
        self._password = password
    
    # -------------------------------------------------------------------------
    # Connection Management
    # -------------------------------------------------------------------------
    
    def connect(self, path: str = None, 
                use_credentials: bool = False,
                username: str = None,
                domain: str = None,
                password: str = None,
                **kwargs) -> bool:
        """
        Connect to the network folder.
        
        Args:
            path: Network path (UNC, smb://, mapped drive, or local folder)
            use_credentials: Whether to use explicit credentials
            username: Username for authentication
            domain: Domain for authentication
            password: Password for authentication (kept in memory only).
                If not provided, any password previously set via set_password()
                or stored on the instance will be reused.
            
        Returns:
            bool: True if connection successful
        """
        if path:
            self._base_path = path
        
        if not self._base_path:
            logging.error("SMB Provider: No path configured")
            self._connected = False
            return False
        
        self._use_credentials = use_credentials
        self._username = username
        self._domain = domain
        if password is not None:
            self._password = password
        
        try:
            resolved, err = self._resolve_base_path(self._base_path)
            if resolved is None:
                # Log the path as the user entered it, not the mangled form.
                logging.error(
                    f"SMB Provider: Path not accessible: {self._base_path}"
                    + (f" ({err})" if err else "")
                )
                self._connected = False
                self._resolved_base_path = None
                self._app_folder_path = None
                return False

            self._resolved_base_path = resolved

            # Create or verify SaveState folder
            self._app_folder_path = os.path.join(resolved, self.APP_FOLDER_NAME)
            
            if not os.path.exists(self._app_folder_path):
                try:
                    os.makedirs(self._app_folder_path)
                    logging.info(f"Created SaveState folder: {self._app_folder_path}")
                except PermissionError as e:
                    logging.error(f"Cannot create folder (permission denied): {e}")
                    self._connected = False
                    self._app_folder_path = None
                    return False
            
            self._connected = True
            logging.info(f"SMB Provider connected: {self._app_folder_path}")
            return True
            
        except Exception as e:
            logging.error(f"SMB Provider connection failed: {e}")
            self._connected = False
            self._resolved_base_path = None
            self._app_folder_path = None
            return False
    
    def disconnect(self) -> bool:
        """Disconnect from the network folder."""
        self._connected = False
        logging.info("SMB Provider disconnected")
        return True
    
    def test_connection(self) -> Dict[str, Any]:
        """Test the connection and return detailed status."""
        result = {
            'success': False,
            'message': '',
            'details': {
                'path': self._base_path,
                'resolved_path': self._resolved_base_path,
                'app_folder': self._app_folder_path,
                'writable': False
            }
        }
        
        if not self._base_path:
            result['message'] = 'No path configured'
            return result
        
        try:
            resolved = self._resolved_base_path
            if not resolved:
                # Resolve on-demand if not yet connected.
                resolved, err = self._resolve_base_path(self._base_path)
                if resolved is None:
                    result['message'] = err or f'Path not accessible: {self._base_path}'
                    return result
                self._resolved_base_path = resolved
                result['details']['resolved_path'] = resolved

            # Check if we can write
            test_file = os.path.join(self._app_folder_path or resolved,
                                     '.savestate_test_write')
            try:
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
                result['details']['writable'] = True
            except (PermissionError, OSError):
                result['message'] = 'Path is read-only'
                return result
            
            result['success'] = True
            result['message'] = 'Connection successful'
            return result
            
        except Exception as e:
            result['message'] = str(e)
            return result

    # -------------------------------------------------------------------------
    # Path resolution (cross-platform)
    # -------------------------------------------------------------------------

    def _resolve_base_path(self, raw_path: str) -> Tuple[Optional[str], Optional[str]]:
        """Resolve a user-supplied network path to a local filesystem path.

        Handles:
          - smb:// URIs          -> UNC on Windows, GVFS mount on Linux
          - \\\\server\\share      -> native UNC on Windows, GVFS mount on Linux
          - Z:\\ mapped drives    -> Windows only
          - /mnt/... local paths -> Linux/macOS

        Returns (resolved_path, error_message).  On success error_message is None.
        """
        share_info = _parse_share_path(raw_path)

        # --- Windows path handling -------------------------------------------------
        if sys.platform.startswith('win'):
            if share_info is not None:
                candidate = _to_windows_unc(share_info)
            else:
                # Local or mapped-drive path. Use normpath safely (Windows-native).
                candidate = os.path.normpath(raw_path)

            if os.path.isdir(candidate):
                return candidate, None
            return None, f"Path not accessible: {candidate}"

        # --- Linux / macOS path handling ------------------------------------------
        # If it's a plain local path (no server/share), just check it directly.
        if share_info is None:
            # Never run normpath on something that starts with backslashes on
            # Linux; normpath would mangle it. raw_path here is a local path.
            if os.path.isdir(raw_path):
                return raw_path, None
            return None, f"Path not accessible: {raw_path}"

        # SMB share on Linux: resolve via GVFS.
        return self._resolve_linux_gvfs(share_info)

    def _resolve_linux_gvfs(self, info: Dict[str, str]) -> Tuple[Optional[str], Optional[str]]:
        """Find (or create) a GVFS mount for an SMB share on Linux.

        GVFS mounts for SMB shares live at:
            /run/user/<UID>/gvfs/smb-share:server=<srv>,share=<share>[,user=<user>][,domain=<dom>]
        """
        try:
            uid = os.getuid()  # type: ignore[attr-defined]
        except AttributeError:
            return None, "GVFS is only available on Linux"

        gvfs_root = f"/run/user/{uid}/gvfs"
        server = info['server']
        share = info['share']
        subpath = info['subpath']

        # 1) Look for an existing mount first (cheap and works with no credentials
        # if the user already mounted the share via their file manager).
        # NOTE: GVFS paths are always POSIX, so use posixpath.join explicitly
        # rather than os.path.join (which follows the host's convention).
        existing = self._find_gvfs_mount(gvfs_root, server, share)
        if existing:
            candidate = posixpath.join(existing, subpath) if subpath else existing
            if os.path.isdir(candidate):
                return candidate, None

        # 2) Try to mount via `gio mount`.
        gio = shutil.which('gio')
        if not gio:
            return None, (
                "SMB share is not mounted and the 'gio' command is not available. "
                "Install gvfs or mount the share in your file manager first."
            )

        smb_uri = f"smb://{server}/{share}"
        logging.info(f"SMB Provider: mounting {smb_uri} via gio")
        mount_err = self._gio_mount(gio, smb_uri)
        if mount_err:
            return None, mount_err

        # 3) Re-scan for the freshly-created mount (GVFS can take a brief
        # moment to expose the mount in the FUSE tree).
        import time
        existing = None
        for _ in range(10):  # up to ~2 seconds total
            existing = self._find_gvfs_mount(gvfs_root, server, share)
            if existing:
                candidate = posixpath.join(existing, subpath) if subpath else existing
                if os.path.isdir(candidate):
                    return candidate, None
                # Mount is there but subpath isn't visible yet — keep waiting.
            time.sleep(0.2)

        if existing:
            return None, f"Mounted share but subfolder not found: {subpath or '/'}"
        return None, "Mount reported success but no GVFS mount was found"

    @staticmethod
    def _find_gvfs_mount(gvfs_root: str, server: str, share: str) -> Optional[str]:
        """Locate the GVFS mount directory for a given server/share, if any.

        GVFS entries look like:
            smb-share:server=<srv>,share=<share>[,user=<user>][,domain=<dom>]
        We parse the comma-separated key=value pairs and require an EXACT
        match on both ``server`` and ``share`` so that e.g. "nas" does not
        accidentally match a mount named "nas2".
        """
        if not os.path.isdir(gvfs_root):
            return None

        server_l = server.lower()
        share_l = share.lower()
        try:
            for entry in os.listdir(gvfs_root):
                if not entry.startswith('smb-share:'):
                    continue
                # Strip the "smb-share:" prefix and split key=value pairs.
                payload = entry[len('smb-share:'):]
                kv = {}
                for part in payload.split(','):
                    if '=' not in part:
                        continue
                    key, _, value = part.partition('=')
                    kv[key.strip().lower()] = value.strip().lower()
                if kv.get('server') == server_l and kv.get('share') == share_l:
                    candidate = posixpath.join(gvfs_root, entry)
                    if os.path.isdir(candidate):
                        return candidate
        except OSError:
            return None
        return None

    def _gio_mount(self, gio_bin: str, smb_uri: str) -> Optional[str]:
        """Invoke `gio mount <smb_uri>`, feeding credentials on stdin.

        `gio mount` prompts interactively for (in order): username, domain,
        password.  We feed whatever we have; empty lines keep defaults
        (e.g. anonymous user).

        Returns None on success, or an error string on failure.
        """
        # Build stdin payload. We always provide 3 lines so gio doesn't block
        # waiting for further input.
        if self._use_credentials:
            # Accept domain in "DOMAIN\\user" or "user@domain" forms.
            user = self._username or ''
            domain = self._domain or ''
            if user and '\\' in user and not domain:
                domain, _, user = user.partition('\\')
            elif user and '@' in user and not domain:
                user, _, domain = user.partition('@')
            password = self._password or ''
        else:
            user = ''
            domain = ''
            password = ''

        stdin_data = f"{user}\n{domain}\n{password}\n"

        try:
            proc = subprocess.run(
                [gio_bin, 'mount', smb_uri],
                input=stdin_data,
                text=True,
                capture_output=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return "Mount operation timed out"
        except OSError as e:
            return f"Failed to run gio: {e}"

        if proc.returncode == 0:
            return None

        # Friendly error extraction.
        err_out = (proc.stderr or proc.stdout or '').strip()
        if not err_out:
            err_out = f"gio mount exited with code {proc.returncode}"

        # Already-mounted is not an error for our purposes.
        if 'already mounted' in err_out.lower():
            return None

        # Detect auth failures to give a clearer message.
        low = err_out.lower()
        if any(tok in low for tok in ('permission denied', 'password', 'authentication', 'logon failure')):
            return "Authentication failed. Check username and password."
        if 'failed to resolve' in low or 'host is down' in low or 'no route' in low:
            return f"Cannot reach server '{smb_uri}'. Check the hostname and network."
        return err_out
    
    # -------------------------------------------------------------------------
    # Backup Operations
    # -------------------------------------------------------------------------
    
    def upload_backup(self, local_path: str, profile_name: str,
                      overwrite: bool = True,
                      max_backups: Optional[int] = None) -> Dict[str, Any]:
        """
        Upload (copy) a backup folder to the network share.
        
        Args:
            local_path: Local path to the backup folder
            profile_name: Name of the profile
            overwrite: If True, overwrite existing files
            max_backups: If set, keep only this many backups
            
        Returns:
            Dict with upload statistics
        """
        result = {
            'ok': False,
            'uploaded_count': 0,
            'skipped_newer_or_same': 0,
            'total_candidates': 0,
            'error': None
        }
        
        if not self.is_connected:
            result['error'] = 'Not connected'
            return result
        
        if not os.path.isdir(local_path):
            result['error'] = f'Local path not found: {local_path}'
            return result
        
        try:
            # Create profile folder on network share
            profile_folder = os.path.join(self._app_folder_path, profile_name)
            os.makedirs(profile_folder, exist_ok=True)
            
            # Get list of .zip files to upload
            zip_files = [f for f in os.listdir(local_path) if f.endswith('.zip')]
            if not zip_files:
                logging.warning(f"No .zip files found in {local_path}")
                result['ok'] = True
                return result
            
            # Sort by modification time (newest first)
            try:
                zip_files_sorted = sorted(
                    zip_files,
                    key=lambda name: os.path.getmtime(os.path.join(local_path, name)),
                    reverse=True
                )
            except Exception:
                zip_files_sorted = zip_files
            
            # Apply max_backups limit
            if max_backups and max_backups > 0:
                files_to_upload = zip_files_sorted[:max_backups]
            else:
                files_to_upload = zip_files_sorted
            
            result['total_candidates'] = len(files_to_upload)
            
            # Upload each file
            for idx, filename in enumerate(files_to_upload, 1):
                # Check for cancellation
                if self._cancelled:
                    result['cancelled'] = True
                    return result
                
                local_file = os.path.join(local_path, filename)
                remote_file = os.path.join(profile_folder, filename)
                
                # Report progress
                if self.progress_callback:
                    self.progress_callback(idx, len(files_to_upload), f"Copying {filename}")
                
                # Check if file exists and compare
                if os.path.exists(remote_file):
                    # Compare MD5 hashes
                    local_md5 = self._compute_md5(local_file)
                    remote_md5 = self._compute_md5(remote_file)
                    
                    if local_md5 and remote_md5 and local_md5 == remote_md5:
                        logging.debug(f"Skipping {filename}: identical content")
                        result['skipped_newer_or_same'] += 1
                        continue
                    
                    # Compare timestamps if MD5 differs
                    if not overwrite:
                        result['skipped_newer_or_same'] += 1
                        continue
                    
                    local_mtime = os.path.getmtime(local_file)
                    remote_mtime = os.path.getmtime(remote_file)
                    
                    if remote_mtime >= local_mtime:
                        logging.debug(f"Skipping {filename}: remote is newer or same")
                        result['skipped_newer_or_same'] += 1
                        continue
                
                # Copy the file
                try:
                    shutil.copy2(local_file, remote_file)
                    result['uploaded_count'] += 1
                    logging.debug(f"Copied {filename} to network share")
                    
                    # Report chunk progress (file size)
                    if self.chunk_callback:
                        file_size = os.path.getsize(local_file)
                        self.chunk_callback(file_size, file_size)
                        
                except Exception as e:
                    logging.error(f"Failed to copy {filename}: {e}")
            
            # Delete old backups if max_backups is set
            if max_backups and max_backups > 0:
                self._cleanup_old_backups(profile_folder, max_backups)
            
            result['ok'] = True
            logging.info(f"Upload complete: {result['uploaded_count']} files copied")
            return result
            
        except Exception as e:
            logging.error(f"Upload failed: {e}")
            result['error'] = str(e)
            return result
    
    def download_backup(self, profile_name: str, local_path: str,
                        overwrite: bool = True,
                        smart_sync: bool = False) -> Dict[str, Any]:
        """
        Download (copy) a backup folder from the network share.
        
        Args:
            profile_name: Name of the profile to download
            local_path: Local path where to save the backup
            overwrite: If True, overwrite existing local files
            smart_sync: If True, only overwrite if remote is newer
            
        Returns:
            Dict with download statistics
        """
        result = {
            'ok': False,
            'downloaded': 0,
            'skipped': 0,
            'failed': 0,
            'total': 0
        }
        
        if not self.is_connected:
            result['error'] = 'Not connected'
            return result
        
        try:
            # Find profile folder on network share
            profile_folder = os.path.join(self._app_folder_path, profile_name)
            
            if not os.path.isdir(profile_folder):
                result['error'] = f'Profile not found: {profile_name}'
                return result
            
            # Create local directory if needed
            os.makedirs(local_path, exist_ok=True)
            
            # Get list of files
            files = os.listdir(profile_folder)
            result['total'] = len(files)
            
            if not files:
                result['ok'] = True
                return result
            
            # Download each file
            for idx, filename in enumerate(files, 1):
                # Check for cancellation
                if self._cancelled:
                    return result
                
                remote_file = os.path.join(profile_folder, filename)
                local_file = os.path.join(local_path, filename)
                
                # Skip directories
                if os.path.isdir(remote_file):
                    continue
                
                # Report progress
                if self.progress_callback:
                    self.progress_callback(idx, len(files), f"Copying {filename}")
                
                # Check if local file exists
                if os.path.exists(local_file):
                    # Compare MD5
                    local_md5 = self._compute_md5(local_file)
                    remote_md5 = self._compute_md5(remote_file)
                    
                    if local_md5 and remote_md5 and local_md5 == remote_md5:
                        result['skipped'] += 1
                        continue
                    
                    if smart_sync:
                        remote_mtime = os.path.getmtime(remote_file)
                        local_mtime = os.path.getmtime(local_file)
                        
                        if local_mtime >= remote_mtime:
                            result['skipped'] += 1
                            continue
                    elif not overwrite:
                        result['skipped'] += 1
                        continue
                
                # Copy the file
                try:
                    shutil.copy2(remote_file, local_file)
                    result['downloaded'] += 1
                    
                    if self.chunk_callback:
                        file_size = os.path.getsize(remote_file)
                        self.chunk_callback(file_size, file_size)
                        
                except Exception as e:
                    logging.error(f"Failed to copy {filename}: {e}")
                    result['failed'] += 1
            
            result['ok'] = True
            return result
            
        except Exception as e:
            logging.error(f"Download failed: {e}")
            result['error'] = str(e)
            return result
    
    def list_cloud_backups(self) -> List[Dict[str, Any]]:
        """List all backup folders on the network share."""
        backups = []
        
        if not self.is_connected:
            return backups
        
        try:
            # List all folders in the app folder
            for item in os.listdir(self._app_folder_path):
                item_path = os.path.join(self._app_folder_path, item)
                
                if not os.path.isdir(item_path):
                    continue
                
                # Count files and calculate size
                file_count = 0
                total_size = 0
                last_modified = None
                
                for file in os.listdir(item_path):
                    file_path = os.path.join(item_path, file)
                    if os.path.isfile(file_path):
                        file_count += 1
                        total_size += os.path.getsize(file_path)
                        
                        mtime = os.path.getmtime(file_path)
                        if last_modified is None or mtime > last_modified:
                            last_modified = mtime
                
                backups.append({
                    'name': item,
                    'file_count': file_count,
                    'size': total_size,
                    'last_modified': datetime.fromtimestamp(last_modified).isoformat() 
                                     if last_modified else None
                })
            
            return backups
            
        except Exception as e:
            logging.error(f"Failed to list backups: {e}")
            return backups
    
    def delete_cloud_backup(self, profile_name: str) -> bool:
        """Delete a backup folder from the network share."""
        if not self.is_connected:
            return False
        
        try:
            profile_folder = os.path.join(self._app_folder_path, profile_name)
            
            if not os.path.isdir(profile_folder):
                logging.warning(f"Profile folder not found: {profile_name}")
                return False
            
            shutil.rmtree(profile_folder)
            logging.info(f"Deleted backup folder: {profile_name}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to delete backup: {e}")
            return False
    
    # -------------------------------------------------------------------------
    # Storage Information
    # -------------------------------------------------------------------------
    
    def get_storage_info(self) -> Optional[Dict[str, Any]]:
        """Get storage space information for the network share."""
        if not self.is_connected:
            return None
        
        try:
            # Get disk usage for the path
            usage = shutil.disk_usage(self._app_folder_path)
            
            # Calculate SaveState folder usage
            app_usage = self._get_folder_size(self._app_folder_path)
            
            return {
                'total': usage.total,
                'used': usage.used,
                'free': usage.free,
                'app_usage': app_usage
            }
            
        except Exception as e:
            logging.error(f"Failed to get storage info: {e}")
            return None
    
    # -------------------------------------------------------------------------
    # Configuration
    # -------------------------------------------------------------------------
    
    def get_config(self) -> Dict[str, Any]:
        """Get provider configuration for persistence."""
        return {
            'base_path': self._base_path,
            'use_credentials': self._use_credentials,
            'username': self._username,
            'domain': self._domain
            # Note: password is NOT stored here
        }
    
    def load_config(self, config: Dict[str, Any]) -> bool:
        """Load provider configuration from saved settings."""
        try:
            self._base_path = config.get('base_path')
            self._use_credentials = config.get('use_credentials', False)
            self._username = config.get('username')
            self._domain = config.get('domain')
            return True
        except Exception as e:
            logging.error(f"Failed to load SMB config: {e}")
            return False
    
    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Get the configuration schema for UI generation."""
        return {
            'base_path': {
                'type': 'path',
                'label': 'Network Path',
                'required': True,
                'default': '',
                'help': 'Path to network share (e.g., \\\\server\\share or /mnt/nas)'
            },
            'use_credentials': {
                'type': 'bool',
                'label': 'Use different credentials',
                'required': False,
                'default': False,
                'help': 'Use explicit username/password instead of current user'
            },
            'username': {
                'type': 'string',
                'label': 'Username',
                'required': False,
                'default': '',
                'help': 'Username for network authentication (domain\\user or user@domain)'
            }
        }
    
    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------
    
    def _compute_md5(self, file_path: str) -> Optional[str]:
        """Compute MD5 hash of a file."""
        try:
            hash_md5 = hashlib.md5()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            logging.debug(f"Failed to compute MD5 for {file_path}: {e}")
            return None
    
    def _get_folder_size(self, folder_path: str) -> int:
        """Calculate total size of a folder in bytes."""
        total_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(folder_path):
                for filename in filenames:
                    file_path = os.path.join(dirpath, filename)
                    total_size += os.path.getsize(file_path)
        except Exception as e:
            logging.debug(f"Error calculating folder size: {e}")
        return total_size
    
    def _cleanup_old_backups(self, profile_folder: str, max_backups: int) -> None:
        """Delete old backups exceeding the max_backups limit."""
        try:
            zip_files = [f for f in os.listdir(profile_folder) if f.endswith('.zip')]
            
            if len(zip_files) <= max_backups:
                return
            
            # Sort by modification time (oldest first)
            zip_files_sorted = sorted(
                zip_files,
                key=lambda name: os.path.getmtime(os.path.join(profile_folder, name))
            )
            
            # Delete oldest files
            files_to_delete = zip_files_sorted[:len(zip_files) - max_backups]
            
            for filename in files_to_delete:
                file_path = os.path.join(profile_folder, filename)
                try:
                    os.remove(file_path)
                    logging.info(f"Deleted old backup: {filename}")
                except Exception as e:
                    logging.warning(f"Failed to delete {filename}: {e}")
                    
        except Exception as e:
            logging.error(f"Error cleaning up old backups: {e}")
