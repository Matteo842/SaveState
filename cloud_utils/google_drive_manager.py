# cloud_utils/google_drive_manager.py
# -*- coding: utf-8 -*-
"""
Google Drive Manager - Handles authentication and file operations with Google Drive API.
This module will manage:
- OAuth2 authentication
- Upload/download of backup files
- Synchronization logic
- Conflict resolution
"""

import os
import io
import logging
import pickle
import time
import datetime
import random
import queue
import threading
import urllib.parse
from typing import Optional, List, Dict, Callable, Any
from pathlib import Path
from PySide6.QtCore import QObject, Signal

# Lazy loading helpers for Google APIs to optimize startup time
Request = None
Credentials = None
InstalledAppFlow = None
build = None
MediaFileUpload = None
MediaIoBaseDownload = None
HttpError = None

def _lazy_init():
    global Request, Credentials, InstalledAppFlow, build, MediaFileUpload, MediaIoBaseDownload, HttpError
    if build is not None:
        return
    from google.auth.transport.requests import Request as _Request
    from google.oauth2.credentials import Credentials as _Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow as _InstalledAppFlow
    from googleapiclient.discovery import build as _build
    from googleapiclient.http import MediaFileUpload as _MediaFileUpload, MediaIoBaseDownload as _MediaIoBaseDownload
    from googleapiclient.errors import HttpError as _HttpError
    
    Request = _Request
    Credentials = _Credentials
    InstalledAppFlow = _InstalledAppFlow
    build = _build
    MediaFileUpload = _MediaFileUpload
    MediaIoBaseDownload = _MediaIoBaseDownload
    HttpError = _HttpError

import hashlib
from cloud_utils.storage_provider import select_zip_files_for_upload
from common.utils import resource_path
from config import get_app_data_folder

# If modifying these scopes, delete the token.pickle file
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# App folder name in Google Drive
APP_FOLDER_NAME = "SaveState Backups"

# In-memory cache TTLs to cut repeated DriveFiles.List traffic (seconds).
FOLDER_FILES_CACHE_TTL_SEC = 90
CLOUD_BACKUPS_LIST_CACHE_TTL_SEC = 45
OAUTH_CALLBACK_HOST = "127.0.0.1"
OAUTH_CALLBACK_TIMEOUT_SEC = 180
OAUTH_SERVER_POLL_SEC = 0.5


class _OAuthCallbackHandler:
    """Capture only a valid OAuth callback, ignoring browser noise such as favicon requests."""

    def __init__(self, expected_state: str):
        self.expected_state = expected_state
        self.authorization_response: Optional[str] = None

    @staticmethod
    def _html_response(title: str, message: str) -> bytes:
        return (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<title>{title}</title></head>"
            "<body style=\"font-family:sans-serif;text-align:center;padding:50px\">"
            f"<h1>{title}</h1><p>{message}</p></body></html>"
        ).encode("utf-8")

    def __call__(self, environ, start_response):
        from wsgiref.util import request_uri

        response_url = request_uri(environ)
        parsed = urllib.parse.urlparse(response_url)
        params = urllib.parse.parse_qs(parsed.query)
        state = params.get("state", [""])[0]

        if parsed.path == "/favicon.ico":
            start_response("204 No Content", [("Content-Length", "0")])
            return [b""]

        if not ("code" in params or "error" in params):
            response = self._html_response(
                "Authorization Pending",
                "This is the SaveState authorization endpoint. Return to the Google sign-in page.",
            )
            start_response("400 Bad Request", [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(response))),
            ])
            return [response]

        if not state or state != self.expected_state:
            logging.warning("Rejected Google OAuth callback with an invalid state")
            response = self._html_response(
                "Authorization Rejected",
                "The authorization state was invalid. Return to SaveState and try again.",
            )
            start_response("400 Bad Request", [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(response))),
            ])
            return [response]

        self.authorization_response = response_url
        if "error" in params:
            title = "Authorization Cancelled"
            message = "Google did not authorize SaveState. You can close this window."
        else:
            title = "Authorization Successful"
            message = "You can close this window and return to SaveState."
        response = self._html_response(title, message)
        start_response("200 OK", [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(response))),
        ])
        return [response]


class GoogleDriveManager:
    """
    Manager class for Google Drive operations.
    Handles authentication, upload, download, and sync of backup files.
    """
    
    def __init__(self):
        """Initialize the Google Drive manager."""
        _lazy_init()
        self.service = None
        self.credentials = None
        self.is_connected = False
        self.app_folder_id = None  # ID of the SaveState folder in Google Drive
        
        # Bundled credentials are read-only; user tokens must survive AppImage
        # extraction and therefore belong in the platform app-data directory.
        self.base_dir = Path(__file__).parent
        self.client_secret_file = Path(resource_path("cloud_utils/client_secret.json"))
        self.token_file = Path(get_app_data_folder()) / "google_drive_token.pickle"
        self._legacy_token_file = self.base_dir / "token.pickle"
        self.last_auth_error = ""
        self._auth_lock = threading.Lock()
        self._manual_callback_urls: queue.Queue[str] = queue.Queue()
        self._oauth_callback_port: Optional[int] = None
        self._oauth_expected_state: Optional[str] = None
        
        # Progress callback
        self.progress_callback: Optional[Callable[[int, int, str], None]] = None
        self.chunk_callback: Optional[Callable[[int, int], None]] = None
        
        # Settings
        self.compression_level = 'standard'  # 'standard', 'maximum', 'stored'
        self.bandwidth_limit_mbps = None  # None = unlimited

        # Retry/backoff configuration (transient errors)
        self._max_retries = 5
        self._base_backoff_seconds = 0.5
        
        # Cancellation support
        self._cancelled = False

        # DriveFiles.List caches (per-folder file lists + aggregated cloud backup index)
        self._folder_files_cache: dict[str, tuple[float, list]] = {}
        self._cloud_backups_cache: tuple[float, list] | None = None
        
    def authenticate(self, auth_url_callback: Optional[Callable[[str], None]] = None) -> bool:
        """
        Authenticate with Google Drive using OAuth2.
        
        Args:
            auth_url_callback: Optional callback that receives the authorization URL.
                              This allows the UI to display the URL for manual browser opening
                              (useful on Linux where webbrowser.open() may fail silently).
        
        Returns:
            bool: True if authentication successful, False otherwise
        """
        if not self._auth_lock.acquire(blocking=False):
            self.last_auth_error = "Another Google Drive authentication attempt is already running."
            logging.warning(self.last_auth_error)
            return False

        self.reset_cancellation()
        self.last_auth_error = ""
        self._discard_manual_callback_urls()
        try:
            creds = None
            
            # Check if we have a saved token
            token_to_load = self.token_file
            if not token_to_load.exists() and self._legacy_token_file.exists():
                token_to_load = self._legacy_token_file
                logging.info("Found legacy Google Drive token; it will be migrated to app data")
            if token_to_load.exists():
                try:
                    with open(token_to_load, 'rb') as token:
                        creds = pickle.load(token)
                    logging.info("Loaded existing Google Drive credentials")
                except Exception as e:
                    logging.warning(f"Error loading token file: {e}")
                    creds = None
            
            # If there are no (valid) credentials available, let the user log in
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        logging.info("Refreshing expired credentials...")
                        creds.refresh(Request())
                        logging.info("Credentials refreshed successfully")
                    except Exception as e:
                        logging.error(f"Error refreshing credentials: {e}")
                        creds = None
                
                # If still no valid creds, start OAuth flow
                if not creds:
                    if not self.client_secret_file.exists():
                        self.last_auth_error = (
                            "Google Drive configuration is missing (client_secret.json was not found)."
                        )
                        logging.error(f"{self.last_auth_error} Path: {self.client_secret_file}")
                        return False
                    
                    try:
                        logging.info("Starting OAuth2 flow...")
                        flow = InstalledAppFlow.from_client_secrets_file(
                            str(self.client_secret_file), SCOPES
                        )
                        
                        import wsgiref.simple_server
                        import webbrowser
                        
                        # Allow HTTP for localhost (required for OAuth on localhost)
                        os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
                        # An explicit IPv4 loopback avoids localhost resolving to
                        # IPv6 while the embedded WSGI server listens on IPv4.
                        wsgi_app = _OAuthCallbackHandler("")
                        local_server = wsgiref.simple_server.make_server(
                            OAUTH_CALLBACK_HOST,
                            0,
                            wsgi_app,
                            handler_class=wsgiref.simple_server.WSGIRequestHandler,
                        )
                        try:
                            port = local_server.server_port
                            redirect_uri = f"http://{OAUTH_CALLBACK_HOST}:{port}/"
                            flow.redirect_uri = redirect_uri
                            auth_url, state = flow.authorization_url(
                                access_type="offline",
                                prompt="consent",
                            )
                            wsgi_app.expected_state = state
                            self._oauth_callback_port = port
                            self._oauth_expected_state = state
                            logging.info(
                                "Google OAuth callback server listening on %s",
                                redirect_uri,
                            )

                            if auth_url_callback:
                                try:
                                    auth_url_callback(auth_url)
                                except Exception as e_cb:
                                    logging.warning(f"Error in auth_url_callback: {e_cb}")

                            try:
                                opened = webbrowser.open(auth_url, new=1)
                                if not opened:
                                    logging.warning("Default browser did not confirm that it opened")
                            except Exception as e_browser:
                                logging.warning(f"Could not open browser: {e_browser}")

                            authorization_response = self._wait_for_oauth_callback(
                                local_server, wsgi_app, state, port
                            )
                        finally:
                            self._oauth_callback_port = None
                            self._oauth_expected_state = None
                            local_server.server_close()

                        if not authorization_response:
                            return False

                        params = urllib.parse.parse_qs(
                            urllib.parse.urlparse(authorization_response).query
                        )
                        if "error" in params:
                            oauth_error = params.get("error_description", params["error"])[0]
                            self.last_auth_error = f"Google authorization was not completed: {oauth_error}"
                            logging.warning(self.last_auth_error)
                            return False

                        flow.fetch_token(authorization_response=authorization_response)
                        creds = flow.credentials
                        logging.info("OAuth2 flow completed successfully")
                        
                    except Exception as e:
                        self.last_auth_error = f"Google OAuth failed: {e}"
                        logging.error(self.last_auth_error, exc_info=True)
                        return False
                
                # Save the credentials for the next run
                try:
                    self.token_file.parent.mkdir(parents=True, exist_ok=True)
                    temporary_token = self.token_file.with_suffix(".tmp")
                    with open(temporary_token, 'wb') as token:
                        pickle.dump(creds, token)
                    os.replace(temporary_token, self.token_file)
                    if os.name != "nt":
                        os.chmod(self.token_file, 0o600)
                    logging.info("Google Drive credentials saved in app data")
                except Exception as e:
                    logging.warning(f"Error saving token file: {e}")
                else:
                    if (
                        token_to_load == self._legacy_token_file
                        and self._legacy_token_file.exists()
                        and self._legacy_token_file != self.token_file
                    ):
                        try:
                            self._legacy_token_file.unlink()
                            logging.info("Removed legacy Google Drive token after migration")
                        except OSError as e:
                            logging.warning(f"Could not remove legacy Google Drive token: {e}")
            
            # Build the service
            try:
                # static_discovery=False forces fetching the API discovery
                # document from the network instead of looking for bundled
                # static JSON files.  Nuitka does not package the data files
                # from googleapiclient/discovery_cache/documents/ so the
                # default static_discovery=True fails with
                # UnknownApiNameOrVersion in compiled builds.
                self.service = build('drive', 'v3', credentials=creds,
                                     static_discovery=False)
                self.credentials = creds
                logging.info("Google Drive service initialized successfully")
                
                # Create or find app folder
                self.app_folder_id = self.create_app_folder()
                if not self.app_folder_id:
                    self.last_auth_error = (
                        "Google Drive connected, but the SaveState backup folder could not be accessed."
                    )
                    logging.warning("Could not create/find app folder")
                    self.service = None
                    self.credentials = None
                    return False
                
                # Only set connected status AFTER app folder is confirmed
                self.is_connected = True
                
                return True
                
            except Exception as e:
                self.last_auth_error = f"Google Drive API initialization failed: {e}"
                logging.error(self.last_auth_error, exc_info=True)
                return False
                
        except Exception as e:
            self.last_auth_error = f"Unexpected Google Drive authentication error: {e}"
            logging.error(self.last_auth_error, exc_info=True)
            return False
        finally:
            self._oauth_callback_port = None
            self._oauth_expected_state = None
            self._auth_lock.release()

    def _discard_manual_callback_urls(self) -> None:
        """Remove callback URLs left by an earlier authentication attempt."""
        while True:
            try:
                self._manual_callback_urls.get_nowait()
            except queue.Empty:
                return

    def submit_auth_callback_url(self, callback_url: str) -> tuple[bool, str]:
        """Submit a browser redirect URL when the browser cannot reach loopback."""
        callback_url = (callback_url or "").strip()
        try:
            parsed = urllib.parse.urlparse(callback_url)
            params = urllib.parse.parse_qs(parsed.query)
            if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
                return False, "Paste the complete localhost URL shown in the browser address bar."
            if not ("code" in params or "error" in params):
                return False, "The URL does not contain a Google authorization result."
            if not self._oauth_expected_state:
                return False, "No Google authorization is currently waiting for a callback."
            if params.get("state", [""])[0] != self._oauth_expected_state:
                return False, "The URL belongs to a different authorization attempt."
            if parsed.port != self._oauth_callback_port:
                return False, "The URL belongs to a different authorization attempt."
        except (TypeError, ValueError):
            return False, "The pasted callback URL is not valid."

        self._manual_callback_urls.put(callback_url)
        return True, ""

    def _wait_for_oauth_callback(
        self, local_server, wsgi_app: _OAuthCallbackHandler, expected_state: str, port: int
    ) -> Optional[str]:
        """Wait for either the HTTP callback or a manually pasted redirect URL."""
        deadline = time.monotonic() + OAUTH_CALLBACK_TIMEOUT_SEC
        while time.monotonic() < deadline:
            if self._cancelled:
                self.last_auth_error = "Google Drive authorization was cancelled."
                logging.info(self.last_auth_error)
                return None

            try:
                manual_url = self._manual_callback_urls.get_nowait()
            except queue.Empty:
                manual_url = None
            if manual_url:
                parsed = urllib.parse.urlparse(manual_url)
                params = urllib.parse.parse_qs(parsed.query)
                if (
                    parsed.hostname in {"127.0.0.1", "localhost"}
                    and parsed.port == port
                    and params.get("state", [""])[0] == expected_state
                ):
                    logging.info("Using manually submitted Google OAuth callback URL")
                    return manual_url

            if wsgi_app.authorization_response:
                return wsgi_app.authorization_response

            remaining = deadline - time.monotonic()
            local_server.timeout = min(OAUTH_SERVER_POLL_SEC, max(0.0, remaining))
            local_server.handle_request()

        self.last_auth_error = (
            "Google authorization timed out because the browser callback was not received. "
            "If the browser shows a failed localhost page, paste its full address into SaveState."
        )
        logging.error(self.last_auth_error)
        return None
    
    def disconnect(self):
        """End the active connection while preserving saved credentials."""
        self.service = None
        self.credentials = None
        self.is_connected = False
        self.app_folder_id = None
        self._invalidate_list_caches()
        logging.info("Disconnected from Google Drive")

    def logout(self) -> bool:
        """Disconnect and delete all current and legacy saved credentials."""
        self.disconnect()
        removed = False
        deletion_errors = []
        for token_path in {self.token_file, self._legacy_token_file}:
            try:
                if token_path.exists():
                    token_path.unlink()
                    removed = True
                    logging.info("Deleted saved Google Drive credentials: %s", token_path)
            except OSError as e:
                deletion_errors.append(f"{token_path}: {e}")

        if deletion_errors:
            raise OSError(
                "Could not delete all saved Google Drive credentials: "
                + "; ".join(deletion_errors)
            )
        return removed

    def _invalidate_list_caches(self, folder_id: str | None = None) -> None:
        """Drop cached list results after mutations or disconnect."""
        if folder_id:
            self._folder_files_cache.pop(folder_id, None)
        else:
            self._folder_files_cache.clear()
        self._cloud_backups_cache = None
    
    def request_cancellation(self):
        """Request cancellation of current operation."""
        self._cancelled = True
        logging.info("GoogleDriveManager: Cancellation requested")
    
    def reset_cancellation(self):
        """Reset cancellation flag (call before starting a new operation)."""
        self._cancelled = False
    
    def is_cancelled(self) -> bool:
        """Check if cancellation was requested."""
        return self._cancelled
    
    def create_app_folder(self) -> Optional[str]:
        """
        Create or find the SaveState folder in Google Drive.
        
        Returns:
            Optional[str]: Folder ID if successful, None otherwise
        """
        if not self.service:
            logging.error("Service not initialized")
            return None
        
        try:
            # Search for existing folder
            query = f"name='{APP_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = self._execute_with_retries(
                lambda: self.service.files().list(
                    q=query,
                    spaces='drive',
                    fields='files(id, name)'
                ).execute(),
                "list app folder"
            )
            
            items = results.get('files', [])
            
            if items:
                folder_id = items[0]['id']
                logging.info(f"Found existing app folder: {folder_id}")
                return folder_id
            
            # Create new folder
            file_metadata = {
                'name': APP_FOLDER_NAME,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            
            folder = self._execute_with_retries(
                lambda: self.service.files().create(
                    body=file_metadata,
                    fields='id'
                ).execute(),
                "create app folder"
            )
            
            folder_id = folder.get('id')
            logging.info(f"Created new app folder: {folder_id}")
            return folder_id
            
        except HttpError as e:
            logging.error(f"HTTP error creating/finding app folder: {e}")
            return None
        except Exception as e:
            logging.error(f"Error creating/finding app folder: {e}")
            return None
    
    def _compute_local_md5(self, file_path: str) -> Optional[str]:
        """Compute MD5 hash of a local file."""
        try:
            hash_md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            logging.error(f"Error computing MD5 for {file_path}: {e}")
            return None

    def _get_remote_md5(self, file_id: str) -> Optional[str]:
        """Get MD5 hash of a remote file from Google Drive metadata."""
        try:
            meta = self._execute_with_retries(
                lambda: self.service.files().get(fileId=file_id, fields='md5Checksum').execute(),
                "get file md5"
            )
            return meta.get('md5Checksum')
        except Exception as e:
            logging.error(f"Error getting MD5 for remote file {file_id}: {e}")
            return None

    def upload_backup(self, local_path: str, profile_name: str, overwrite: bool = True, 
                      max_backups: Optional[int] = None, latest_only: bool = False) -> Dict[str, any]:
        """
        Upload a backup folder to Google Drive.
        
        Args:
            local_path: Local path to the backup folder
            profile_name: Name of the profile (used as folder name in Drive)
            overwrite: If True, overwrite existing files; if False, skip existing
            max_backups: If set, keep only this many backups (delete oldest after upload)
            
        Returns:
            bool: True if upload successful, False otherwise
        """
        if not self.service or not self.app_folder_id:
            logging.error("Not connected to Google Drive")
            return False
        
        if not os.path.isdir(local_path):
            logging.error(f"Local path is not a directory: {local_path}")
            return False
        
        try:
            # Get or create profile folder in Drive
            profile_folder_id = self._get_or_create_folder(profile_name, self.app_folder_id)
            if not profile_folder_id:
                logging.error(f"Could not create profile folder: {profile_name}")
                return False
            
            # Get list of .zip files to upload (newest first; optional latest-only)
            files_to_upload = select_zip_files_for_upload(
                local_path, max_backups=max_backups, latest_only=latest_only,
            )
            if not files_to_upload:
                logging.warning(f"No .zip files found in {local_path}")
                return {'ok': True, 'uploaded_count': 0, 'skipped_newer_or_same': 0, 'total_candidates': 0}
            
            logging.info(f"Uploading {len(files_to_upload)} files for profile '{profile_name}'...")

            uploaded_count = 0
            skipped_newer_or_same = 0

            # One DriveFiles.List per profile folder (not one per zip file).
            remote_files_by_name: dict[str, dict] = {}
            if overwrite:
                for file_meta in self._list_files_in_folder(profile_folder_id):
                    name = file_meta.get('name')
                    if name:
                        remote_files_by_name[name] = file_meta
            
            # Upload each file
            for idx, filename in enumerate(files_to_upload, 1):
                # Check for cancellation before each file
                if self._cancelled:
                    logging.info(f"Upload cancelled for profile '{profile_name}'")
                    return {
                        'ok': False,
                        'cancelled': True,
                        'uploaded_count': uploaded_count,
                        'skipped_newer_or_same': skipped_newer_or_same,
                        'total_candidates': len(files_to_upload)
                    }
                
                file_path = os.path.join(local_path, filename)
                
                # Report progress
                if self.progress_callback:
                    self.progress_callback(idx, len(files_to_upload), f"Uploading {filename}")
                
                # Check if file already exists in Drive (from folder listing above)
                existing_meta = remote_files_by_name.get(filename) if overwrite else None
                existing_file_id = existing_meta.get('id') if existing_meta else None
                
                if existing_file_id:
                    # CHECK 1: MD5 Hash Comparison (Strong Integrity Check)
                    local_md5 = self._compute_local_md5(file_path)
                    remote_md5 = (existing_meta or {}).get('md5Checksum')
                    if not remote_md5:
                        remote_md5 = self._get_remote_md5(existing_file_id)
                    
                    if local_md5 and remote_md5 and local_md5 == remote_md5:
                        logging.info(f"Skipping upload for '{filename}': content identical (MD5 match)")
                        skipped_newer_or_same += 1
                        continue

                    # CHECK 2: Timestamp Fallback (if MD5s differ or check failed)
                    try:
                        if not self._is_local_newer_from_meta(file_path, existing_meta):
                            logging.info(f"Skipping upload for '{filename}': cloud version is newer or same age")
                            skipped_newer_or_same += 1
                            continue
                    except Exception as e_cmp:
                        logging.debug(f"Could not compare modified times for '{filename}': {e_cmp}. Proceeding conservatively with update.")
                    
                    # Update existing file
                    success = self._update_file(existing_file_id, file_path)
                    
                    # Check for cancellation immediately after upload attempt
                    if self._cancelled:
                        logging.info(f"Upload cancelled during file '{filename}'")
                        return {
                            'ok': False,
                            'cancelled': True,
                            'uploaded_count': uploaded_count,
                            'skipped_newer_or_same': skipped_newer_or_same,
                            'total_candidates': len(files_to_upload)
                        }
                    
                    if success:
                        logging.info(f"Updated file: {filename}")
                        uploaded_count += 1
                        self._invalidate_list_caches(profile_folder_id)
                    else:
                        logging.warning(f"Failed to update file: {filename}")
                else:
                    # Upload new file
                    success = self._upload_file(file_path, filename, profile_folder_id)
                    
                    # Check for cancellation immediately after upload attempt
                    if self._cancelled:
                        logging.info(f"Upload cancelled during file '{filename}'")
                        return {
                            'ok': False,
                            'cancelled': True,
                            'uploaded_count': uploaded_count,
                            'skipped_newer_or_same': skipped_newer_or_same,
                            'total_candidates': len(files_to_upload)
                        }
                    
                    if success:
                        logging.info(f"Uploaded file: {filename}")
                        uploaded_count += 1
                        self._invalidate_list_caches(profile_folder_id)
                    else:
                        logging.warning(f"Failed to upload file: {filename}")
            
            logging.info(f"Upload completed for profile '{profile_name}'")
            
            # IMPORTANT: Cleanup old backups AFTER successful upload (safety first!)
            if max_backups and max_backups > 0 and not latest_only:
                self._cleanup_old_backups(profile_folder_id, profile_name, max_backups)
            
            return {
                'ok': True,
                'uploaded_count': uploaded_count,
                'skipped_newer_or_same': skipped_newer_or_same,
                'total_candidates': len(files_to_upload)
            }
            
        except Exception as e:
            logging.error(f"Error uploading backup: {e}")
            return {'ok': False, 'error': str(e), 'uploaded_count': 0, 'skipped_newer_or_same': 0, 'total_candidates': 0}
    
    def download_backup(self, profile_name: str, local_path: str, overwrite: bool = True, smart_sync: bool = False) -> Dict[str, any]:
        """
        Download a backup folder from Google Drive.
        
        Args:
            profile_name: Name of the profile to download
            local_path: Local path where to save the backup
            overwrite: If True, overwrite existing local files; if False, skip existing
            smart_sync: If True, only overwrite if cloud file is strictly newer
            
        Returns:
            Dict: Download statistics
        """
        result_stats = {
            'ok': False,
            'downloaded': 0,
            'skipped': 0,
            'failed': 0,
            'total': 0
        }

        if not self.service or not self.app_folder_id:
            logging.error("Not connected to Google Drive")
            return result_stats
        
        try:
            # Find profile folder in Drive
            profile_folder_id = self._find_folder(profile_name, self.app_folder_id)
            if not profile_folder_id:
                logging.error(f"Profile folder not found in Drive: {profile_name}")
                return result_stats
            
            # Create local directory if it doesn't exist
            os.makedirs(local_path, exist_ok=True)
            
            # List all files in the profile folder (include md5Checksum field)
            files = self._list_files_in_folder(profile_folder_id)
            result_stats['total'] = len(files)
            
            if not files:
                logging.warning(f"No files found in cloud folder: {profile_name}")
                result_stats['ok'] = True
                return result_stats
            
            logging.info(f"Downloading {len(files)} files for profile '{profile_name}'...")
            
            # Download each file
            for idx, file_info in enumerate(files, 1):
                # Check for cancellation before each file
                if self._cancelled:
                    logging.info(f"Download cancelled for profile '{profile_name}'")
                    result_stats['ok'] = False
                    return result_stats
                
                file_id = file_info['id']
                filename = file_info['name']
                remote_md5 = file_info.get('md5Checksum')
                local_file_path = os.path.join(local_path, filename)
                
                # Report progress
                if self.progress_callback:
                    self.progress_callback(idx, len(files), f"Downloading {filename}")
                
                # Check local file if exists
                if os.path.exists(local_file_path):
                    # If checksum matches, skip download regardless of overwrite setting
                    if remote_md5:
                        local_md5 = self._compute_local_md5(local_file_path)
                        if local_md5 and local_md5 == remote_md5:
                            logging.info(f"Skipping download for '{filename}': file exists and MD5 matches")
                            result_stats['skipped'] += 1
                            continue
                    
                    # Smart Sync: Skip if local is newer
                    if smart_sync:
                        remote_mtime = file_info.get('modifiedTime')
                        if not self._is_remote_newer(local_file_path, remote_mtime):
                            logging.info(f"Skipping download for '{filename}': local version is newer or same age")
                            result_stats['skipped'] += 1
                            continue
                    # If not matching, skip only if overwrite is False
                    elif not overwrite:
                        logging.info(f"Skipping existing file: {filename}")
                        result_stats['skipped'] += 1
                        continue
                
                # Download file
                success = self._download_file(file_id, local_file_path)
                
                # Check for cancellation immediately after download attempt
                if self._cancelled:
                    logging.info(f"Download cancelled during file '{filename}'")
                    result_stats['ok'] = False
                    return result_stats
                
                if success:
                    # Verify integrity after download
                    if remote_md5:
                        new_local_md5 = self._compute_local_md5(local_file_path)
                        if new_local_md5 != remote_md5:
                            logging.error(f"Integrity check failed for {filename}! Remote MD5: {remote_md5}, Local MD5: {new_local_md5}")
                            # Delete corrupted file
                            try:
                                os.remove(local_file_path)
                                logging.info(f"Deleted corrupted file: {local_file_path}")
                            except Exception as e_del:
                                logging.error(f"Failed to delete corrupted file: {e_del}")
                            result_stats['failed'] += 1
                            return result_stats # Fail whole batch on corruption? Or just count? Usually fail safe.
                        else:
                            logging.info(f"Downloaded and verified file: {filename}")
                            result_stats['downloaded'] += 1
                    else:
                        logging.info(f"Downloaded file (no remote MD5): {filename}")
                        result_stats['downloaded'] += 1
                else:
                    logging.warning(f"Failed to download file: {filename}")
                    result_stats['failed'] += 1
            
            logging.info(f"Download completed for profile '{profile_name}'")
            result_stats['ok'] = True
            return result_stats
            
        except Exception as e:
            logging.error(f"Error downloading backup: {e}")
            result_stats['ok'] = False
            return result_stats
    
    def list_cloud_backups(self) -> List[Dict[str, any]]:
        """
        List all backup folders available in Google Drive.
        
        Returns:
            List[Dict]: List of backup info dictionaries with keys:
                - name: Profile name
                - file_count: Number of backup files
                - last_modified: Last modification date
                - size: Total size in bytes
        """
        if not self.service or not self.app_folder_id:
            logging.error("Not connected to Google Drive")
            return []

        if self._cloud_backups_cache is not None:
            cached_at, cached_data = self._cloud_backups_cache
            if time.monotonic() - cached_at < CLOUD_BACKUPS_LIST_CACHE_TTL_SEC:
                logging.debug("Returning cached cloud backup list")
                return cached_data
        
        try:
            # List all folders in the app folder
            query = f"'{self.app_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = self._execute_with_retries(
                lambda: self.service.files().list(
                    q=query,
                    spaces='drive',
                    fields='files(id, name, modifiedTime)',
                    orderBy='name'
                ).execute(),
                "list cloud backup folders"
            )
            
            folders = results.get('files', [])
            backups = []
            
            for folder in folders:
                folder_id = folder['id']
                folder_name = folder['name']
                
                # Get files in this folder
                files = self._list_files_in_folder(folder_id)
                
                # Calculate total size and get latest modification time
                total_size = 0
                last_modified = folder.get('modifiedTime', '')
                
                for file_info in files:
                    total_size += int(file_info.get('size', 0))
                    file_modified = file_info.get('modifiedTime', '')
                    if file_modified > last_modified:
                        last_modified = file_modified
                
                backups.append({
                    'name': folder_name,
                    'file_count': len(files),
                    'last_modified': last_modified,
                    'size': total_size
                })
            
            logging.info(f"Found {len(backups)} backup folders in cloud")
            self._cloud_backups_cache = (time.monotonic(), backups)
            return backups
            
        except HttpError as e:
            logging.error(f"HTTP error listing cloud backups: {e}")
            return []
        except Exception as e:
            logging.error(f"Error listing cloud backups: {e}")
            return []
    
    def sync_backup(self, profile_name: str, local_path: str, 
                    direction: str = "bidirectional") -> Dict[str, any]:
        """
        Synchronize a backup between local and cloud.
        
        Args:
            profile_name: Name of the profile to sync
            local_path: Local path to the backup folder
            direction: Sync direction - "upload", "download", or "bidirectional"
            
        Returns:
            Dict: Sync result with 'ok' key indicating success
        """
        if direction == "upload":
            return self.upload_backup(local_path, profile_name, overwrite=True)
        elif direction == "download":
            return self.download_backup(profile_name, local_path, overwrite=True)
        elif direction == "bidirectional":
            # For bidirectional, we'll use a simple strategy:
            # 1. Upload all local files (overwriting older cloud files)
            # 2. Download any cloud files that don't exist locally
            
            # First upload
            upload_result = self.upload_backup(local_path, profile_name, overwrite=True)
            if not upload_result.get('ok', False):
                logging.error("Upload phase of bidirectional sync failed")
                return {'ok': False, 'error': 'Upload phase failed', 'phase': 'upload'}
            
            # Then download (smart sync: only overwrite if remote is newer)
            download_result = self.download_backup(profile_name, local_path, overwrite=True, smart_sync=True)
            if not download_result.get('ok', False):
                logging.error("Download phase of bidirectional sync failed")
                return {'ok': False, 'error': 'Download phase failed', 'phase': 'download'}
            
            logging.info(f"Bidirectional sync completed for profile '{profile_name}'")
            return {
                'ok': True,
                'upload': upload_result,
                'download': download_result
            }
        else:
            logging.error(f"Invalid sync direction: {direction}")
            return {'ok': False, 'error': f'Invalid sync direction: {direction}'}
    
    def delete_cloud_backup(self, profile_name: str) -> bool:
        """
        Delete a backup folder from Google Drive.
        
        Args:
            profile_name: Name of the profile to delete
            
        Returns:
            bool: True if deletion successful, False otherwise
        """
        if not self.service or not self.app_folder_id:
            logging.error("Not connected to Google Drive")
            return False
        
        try:
            # Find profile folder
            profile_folder_id = self._find_folder(profile_name, self.app_folder_id)
            if not profile_folder_id:
                logging.warning(f"Profile folder not found in Drive: {profile_name}")
                return False
            
            # Delete the folder (this will also delete all files inside)
            self._execute_with_retries(
                lambda: self.service.files().delete(fileId=profile_folder_id).execute(),
                "delete cloud backup folder"
            )
            logging.info(f"Deleted cloud backup folder: {profile_name}")
            self._invalidate_list_caches(profile_folder_id)
            return True
            
        except HttpError as e:
            logging.error(f"HTTP error deleting cloud backup: {e}")
            return False
        except Exception as e:
            logging.error(f"Error deleting cloud backup: {e}")
            return False
    
    def get_storage_info(self) -> Optional[Dict[str, int]]:
        """
        Get Google Drive storage information.
        
        Returns:
            Optional[Dict]: Dictionary with keys:
                - total: Total storage in bytes
                - used: Used storage in bytes
                - free: Free storage in bytes
            None if not connected or error
        """
        if not self.service:
            logging.error("Not connected to Google Drive")
            return None
        
        try:
            about = self._execute_with_retries(
                lambda: self.service.about().get(fields='storageQuota').execute(),
                "get storage info"
            )
            quota = about.get('storageQuota', {})
            
            total = int(quota.get('limit', 0))
            used = int(quota.get('usage', 0))
            free = total - used if total > 0 else 0
            
            return {
                'total': total,
                'used': used,
                'free': free
            }
            
        except HttpError as e:
            logging.error(f"HTTP error getting storage info: {e}")
            return None
        except Exception as e:
            logging.error(f"Error getting storage info: {e}")
            return None
    
    # ========== Helper Methods ==========
    
    def _get_or_create_folder(self, folder_name: str, parent_id: str) -> Optional[str]:
        """Get existing folder ID or create new folder."""
        # Try to find existing folder
        folder_id = self._find_folder(folder_name, parent_id)
        if folder_id:
            return folder_id
        
        # Create new folder
        try:
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [parent_id]
            }
            
            folder = self.service.files().create(
                body=file_metadata,
                fields='id'
            ).execute()
            
            return folder.get('id')
            
        except Exception as e:
            logging.error(f"Error creating folder '{folder_name}': {e}")
            return None
    
    @staticmethod
    def _escape_query_string(value: str) -> str:
        """Escape a string value for use in Google Drive API queries.
        
        Google Drive API uses single quotes for string values in queries.
        Single quotes within the value must be escaped by doubling them.
        Backslashes must also be escaped.
        """
        # Escape backslashes first, then single quotes
        return value.replace('\\', '\\\\').replace("'", "\\'")
    
    def _find_folder(self, folder_name: str, parent_id: str) -> Optional[str]:
        """Find a folder by name in a parent folder."""
        try:
            escaped_name = self._escape_query_string(folder_name)
            query = f"name='{escaped_name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = self._execute_with_retries(
                lambda: self.service.files().list(
                    q=query,
                    spaces='drive',
                    fields='files(id)'
                ).execute(),
                "find folder"
            )
            
            items = results.get('files', [])
            return items[0]['id'] if items else None
            
        except Exception as e:
            logging.error(f"Error finding folder '{folder_name}': {e}")
            return None
    
    def _find_file_in_folder(self, filename: str, folder_id: str) -> Optional[str]:
        """Find a file by name in a folder."""
        try:
            escaped_filename = self._escape_query_string(filename)
            query = f"name='{escaped_filename}' and '{folder_id}' in parents and trashed=false"
            results = self._execute_with_retries(
                lambda: self.service.files().list(
                    q=query,
                    spaces='drive',
                    fields='files(id)'
                ).execute(),
                "find file"
            )
            
            items = results.get('files', [])
            return items[0]['id'] if items else None
            
        except Exception as e:
            logging.error(f"Error finding file '{filename}': {e}")
            return None

    @staticmethod
    def _parse_drive_timestamp(ts: str) -> Optional[float]:
        """Parse Google Drive timestamp string to epoch seconds."""
        if not ts:
            return None
        try:
            # Convert RFC3339 to aware datetime
            dt = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except Exception:
            # Fallback: strip sub-seconds
            if 'T' in ts:
                try:
                    main = ts.split('.', 1)[0].replace('Z', '')
                    dt = datetime.datetime.fromisoformat(main + '+00:00')
                except Exception:
                    return None
            else:
                return None
        return dt.timestamp()

    def _is_remote_newer(self, local_path: str, remote_ts_str: str) -> bool:
        """True if the remote file is strictly newer than the local file."""
        if not os.path.exists(local_path):
            return True
            
        try:
            local_ts = os.path.getmtime(local_path)
        except Exception:
            return False
            
        remote_ts = self._parse_drive_timestamp(remote_ts_str)
        if remote_ts is None:
            return False
            
        return remote_ts > local_ts

    def _get_file_modified_time(self, file_id: str) -> Optional[float]:
        """Return the Drive file modified time as epoch seconds (UTC)."""
        try:
            meta = self._execute_with_retries(
                lambda: self.service.files().get(fileId=file_id, fields='modifiedTime').execute(),
                "get file modified time"
            )
            ts = meta.get('modifiedTime')
            return self._parse_drive_timestamp(ts)
        except Exception as e:
            logging.debug(f"Unable to read modifiedTime for file {file_id}: {e}")
            return None

    def _is_local_newer(self, local_path: str, remote_file_id: str) -> bool:
        """True if the local file's mtime is strictly newer than the cloud file."""
        try:
            local_ts = os.path.getmtime(local_path)
        except Exception:
            return True  # If we cannot read mtime, allow upload
        remote_ts = self._get_file_modified_time(remote_file_id)
        if remote_ts is None:
            return True
        return local_ts > remote_ts

    def _is_local_newer_from_meta(self, local_path: str, remote_meta: dict) -> bool:
        """Like _is_local_newer but uses metadata from a folder listing (no extra Get)."""
        try:
            local_ts = os.path.getmtime(local_path)
        except Exception:
            return True
        remote_ts = self._parse_drive_timestamp((remote_meta or {}).get('modifiedTime', ''))
        if remote_ts is None:
            return True
        return local_ts > remote_ts

    # ===== Retry helpers =====
    def _should_retry_http_error(self, error: HttpError) -> bool:
        try:
            status = int(getattr(error, "status_code", None) or getattr(error.resp, "status", 0))
        except Exception:
            status = 0
        # Retry on common transient statuses
        return status in (408, 429, 500, 502, 503, 504)

    def _sleep_with_backoff(self, attempt: int, context: str):
        try:
            delay = self._base_backoff_seconds * (2 ** attempt)
            delay = delay + random.uniform(0, 0.25)  # jitter
            capped = min(delay, 8.0)
            logging.warning(f"Transient error during {context}. Backing off for {capped:.2f}s (attempt {attempt+1}/{self._max_retries})")
            time.sleep(capped)
        except Exception as e:
            logging.error(f"Error during sleep backoff: {e}")

    def _execute_with_retries(self, func: Callable[[], any], description: str):
        last_exc = None
        for attempt in range(self._max_retries):
            try:
                return func()
            except HttpError as e:
                if self._should_retry_http_error(e):
                    self._sleep_with_backoff(attempt, description)
                    last_exc = e
                    continue
                last_exc = e
                break
            except Exception as e:  # Catch ALL exceptions to be safe against crashes during retry logic
                # Check if it's one of the known transient errors or just something unexpected
                # We retry on almost everything during connection/upload phases to prevent crashes
                # unless it's clearly fatal.
                is_likely_transient = isinstance(e, (OSError, TimeoutError, ConnectionError))
                
                # Also catch generic Exceptions that might be transient network glitches
                self._sleep_with_backoff(attempt, f"{description} ({type(e).__name__})")
                last_exc = e
                continue
                
        # Exhausted retries or non-retryable
        if last_exc:
            logging.error(f"{description} failed after retries: {last_exc}")
            raise last_exc
    
    def _list_files_in_folder(self, folder_id: str, *, use_cache: bool = True) -> List[Dict]:
        """List all files in a folder."""
        if not self.service:
            logging.debug("Service unavailable during file list request, skipping.")
            return []

        if use_cache and folder_id in self._folder_files_cache:
            cached_at, cached_files = self._folder_files_cache[folder_id]
            if time.monotonic() - cached_at < FOLDER_FILES_CACHE_TTL_SEC:
                return cached_files
            
        try:
            query = f"'{folder_id}' in parents and trashed=false"
            results = self._execute_with_retries(
                lambda: self.service.files().list(
                    q=query,
                    spaces='drive',
                    fields='files(id, name, size, modifiedTime, md5Checksum)',
                    orderBy='name'
                ).execute(),
                "list files in folder"
            )
            
            files = results.get('files', [])
            self._folder_files_cache[folder_id] = (time.monotonic(), files)
            return files
            
        except Exception as e:
            # Don't log full traceback for simple "service is gone" errors during disconnection
            if "'NoneType' object has no attribute 'files'" in str(e):
                logging.warning("Could not list files: Service was disconnected during operation.")
            else:
                logging.error(f"Error listing files in folder: {e}")
            return []
    
    def _upload_file(self, file_path: str, filename: str, parent_id: str) -> bool:
        """Upload a file to Google Drive."""
        try:
            file_metadata = {
                'name': filename,
                'parents': [parent_id]
            }
            
            # Choose chunk size to improve throttling granularity (multiple of 256KB)
            chunk_size = 1024 * 1024 if self.bandwidth_limit_mbps else None
            if chunk_size is not None:
                media = MediaFileUpload(file_path, resumable=True, chunksize=chunk_size)
            else:
                media = MediaFileUpload(file_path, resumable=True)
            
            request = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            )
            
            response = None
            total_size = os.path.getsize(file_path)
            
            if self.chunk_callback:
                self.chunk_callback(0, total_size)
                
            prev_bytes = 0
            t_prev = time.time()
            attempt = 0
            while response is None:
                # Check for cancellation
                if self._cancelled:
                    logging.info(f"Upload cancelled during file '{filename}'")
                    return False
                
                try:
                    status, response = request.next_chunk()
                except HttpError as e:
                    if self._should_retry_http_error(e) and attempt < self._max_retries:
                        self._sleep_with_backoff(attempt, "upload chunk")
                        attempt += 1
                        continue
                    raise
                if status:
                    # Progress reporting
                    progress = int(status.progress() * 100)
                    logging.debug(f"Upload progress: {progress}%")
                    
                    if self.chunk_callback:
                        current_bytes = int(status.progress() * total_size)
                        self.chunk_callback(current_bytes, total_size)

                    # Bandwidth throttling
                    try:
                        if self.bandwidth_limit_mbps:
                            curr_bytes = int(status.progress() * total_size)
                            delta = max(0, curr_bytes - prev_bytes)
                            prev_bytes = curr_bytes
                            t_now = time.time()
                            elapsed = max(1e-6, t_now - t_prev)
                            limit_bps = self.bandwidth_limit_mbps * 1024 * 1024 / 8.0
                            desired = delta / limit_bps if limit_bps > 0 else 0
                            if desired > elapsed:
                                time.sleep(desired - elapsed)
                            t_prev = time.time()
                    except Exception:
                        pass
            
            if self.chunk_callback:
                self.chunk_callback(total_size, total_size)

            return True
            
        except Exception as e:
            logging.error(f"Error uploading file '{filename}': {e}")
            return False
    
    def _update_file(self, file_id: str, file_path: str) -> bool:
        """Update an existing file in Google Drive."""
        try:
            chunk_size = 1024 * 1024 if self.bandwidth_limit_mbps else None
            if chunk_size is not None:
                media = MediaFileUpload(file_path, resumable=True, chunksize=chunk_size)
            else:
                media = MediaFileUpload(file_path, resumable=True)
            
            request = self.service.files().update(
                fileId=file_id,
                media_body=media
            )
            
            response = None
            total_size = os.path.getsize(file_path)
            
            if self.chunk_callback:
                self.chunk_callback(0, total_size)
                
            prev_bytes = 0
            t_prev = time.time()
            attempt = 0
            while response is None:
                # Check for cancellation
                if self._cancelled:
                    logging.info(f"Update cancelled during file (id: {file_id})")
                    return False
                
                try:
                    status, response = request.next_chunk()
                except HttpError as e:
                    if self._should_retry_http_error(e) and attempt < self._max_retries:
                        self._sleep_with_backoff(attempt, "update chunk")
                        attempt += 1
                        continue
                    raise
                if status:
                    progress = int(status.progress() * 100)
                    logging.debug(f"Update progress: {progress}%")
                    
                    if self.chunk_callback:
                        current_bytes = int(status.progress() * total_size)
                        self.chunk_callback(current_bytes, total_size)

                    try:
                        if self.bandwidth_limit_mbps:
                            curr_bytes = int(status.progress() * total_size)
                            delta = max(0, curr_bytes - prev_bytes)
                            prev_bytes = curr_bytes
                            t_now = time.time()
                            elapsed = max(1e-6, t_now - t_prev)
                            limit_bps = self.bandwidth_limit_mbps * 1024 * 1024 / 8.0
                            desired = delta / limit_bps if limit_bps > 0 else 0
                            if desired > elapsed:
                                time.sleep(desired - elapsed)
                            t_prev = time.time()
                    except Exception:
                        pass
            
            if self.chunk_callback:
                self.chunk_callback(total_size, total_size)

            return True
            
        except Exception as e:
            logging.error(f"Error updating file: {e}")
            return False
    
    def _download_file(self, file_id: str, destination_path: str) -> bool:
        """Download a file from Google Drive."""
        fh = None
        try:
            request = self.service.files().get_media(fileId=file_id)
            
            fh = io.FileIO(destination_path, 'wb')
            # Determine total size for throttling computation
            try:
                meta = self._execute_with_retries(
                    lambda: self.service.files().get(fileId=file_id, fields='size').execute(),
                    "get file size for download"
                )
                total_size = int(meta.get('size', 0))
            except Exception:
                total_size = 0

            # Determine chunk size to match upload behavior
            # If bandwidth limit is enabled, use 1MB chunks for better throttling granularity
            # If disabled (None), use default chunk size (usually 100MB+) for max speed
            chunk_size = 1024 * 1024 if self.bandwidth_limit_mbps else None
            
            if chunk_size:
                downloader = MediaIoBaseDownload(fh, request, chunksize=chunk_size)
            else:
                downloader = MediaIoBaseDownload(fh, request)
            
            if self.chunk_callback:
                self.chunk_callback(0, total_size)
            
            done = False
            prev_bytes = 0
            t_prev = time.time()
            attempt = 0
            while not done:
                # Check for cancellation
                if self._cancelled:
                    fh.close()
                    fh = None  # Mark as closed to prevent double-close in finally
                    # Try to delete partial file
                    try:
                        if os.path.exists(destination_path):
                            os.remove(destination_path)
                            logging.info(f"Deleted partial download: {destination_path}")
                    except Exception as e_del:
                        logging.warning(f"Could not delete partial download: {e_del}")
                    logging.info(f"Download cancelled during file (id: {file_id})")
                    return False
                
                try:
                    status, done = downloader.next_chunk()
                except HttpError as e:
                    if self._should_retry_http_error(e) and attempt < self._max_retries:
                        self._sleep_with_backoff(attempt, "download chunk")
                        attempt += 1
                        continue
                    raise
                if status:
                    progress = int(status.progress() * 100)
                    logging.debug(f"Download progress: {progress}%")
                    
                    if self.chunk_callback:
                        current_bytes = int(status.progress() * total_size)
                        self.chunk_callback(current_bytes, total_size)
                    
                    # Throttle
                    try:
                        if self.bandwidth_limit_mbps and total_size:
                            curr_bytes = int(status.progress() * total_size)
                            delta = max(0, curr_bytes - prev_bytes)
                            prev_bytes = curr_bytes
                            t_now = time.time()
                            elapsed = max(1e-6, t_now - t_prev)
                            limit_bps = self.bandwidth_limit_mbps * 1024 * 1024 / 8.0
                            desired = delta / limit_bps if limit_bps > 0 else 0
                            if desired > elapsed:
                                time.sleep(desired - elapsed)
                            t_prev = time.time()
                    except Exception:
                        pass
            
            if self.chunk_callback:
                self.chunk_callback(total_size, total_size)
                
            fh.close()
            fh = None  # Mark as closed
            return True
            
        except Exception as e:
            logging.error(f"Error downloading file: {e}")
            return False
        finally:
            # Ensure file handle is always closed, even on exception
            if fh is not None:
                try:
                    fh.close()
                except Exception:
                    pass
    
    def set_progress_callback(self, callback: Callable[[int, int, str], None]):
        """Set a callback function for progress updates."""
        self.progress_callback = callback

    def set_chunk_callback(self, callback: Callable[[int, int], None]):
        """
        Set a callback function for chunk-level progress updates (byte-level).
        Args:
            callback: Function accepting (current_bytes, total_bytes)
        """
        self.chunk_callback = callback
    
    def set_compression_level(self, level: str):
        """
        Set compression level for uploads.
        
        Args:
            level: 'standard', 'maximum', or 'stored' (no compression)
        """
        if level in ['standard', 'maximum', 'stored']:
            self.compression_level = level
            logging.debug(f"Compression level set to: {level}")
        else:
            logging.warning(f"Invalid compression level: {level}")
    
    def set_bandwidth_limit(self, limit_mbps: Optional[int]):
        """
        Set bandwidth limit for uploads/downloads.
        
        Args:
            limit_mbps: Limit in Mbps, or None for unlimited
        """
        self.bandwidth_limit_mbps = limit_mbps
        if limit_mbps:
            logging.debug(f"Bandwidth limit set to: {limit_mbps} Mbps")
        else:
            logging.debug("Bandwidth limit disabled")
    
    def get_app_folder_size(self) -> int:
        """
        Calculate total size of all files in the SaveState app folder.
        
        Returns:
            int: Total size in bytes, or 0 if error
        """
        if not self.service or not self.app_folder_id:
            return 0
        
        try:
            total_size = 0
            
            # Get all folders in app folder
            folders_query = f"'{self.app_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
            folders_result = self._execute_with_retries(
                lambda: self.service.files().list(
                    q=folders_query,
                    spaces='drive',
                    fields='files(id)'
                ).execute(),
                "list folders for size"
            )
            
            folders = folders_result.get('files', [])
            
            # For each folder, get all files and sum sizes
            for folder in folders:
                folder_id = folder['id']
                files = self._list_files_in_folder(folder_id)
                for file_info in files:
                    total_size += int(file_info.get('size', 0))
            
            return total_size
            
        except Exception as e:
            logging.error(f"Error calculating app folder size: {e}")
            return 0
    
    def check_storage_limit(self, max_gb: int) -> tuple[bool, int, int]:
        """
        Check if current storage is within limit.
        
        Args:
            max_gb: Maximum storage in GB
            
        Returns:
            tuple: (within_limit, current_gb, max_gb)
        """
        try:
            current_bytes = self.get_app_folder_size()
            current_gb = current_bytes / (1024**3)
            within_limit = current_gb < max_gb
            
            return (within_limit, round(current_gb, 2), max_gb)
            
        except Exception as e:
            logging.error(f"Error checking storage limit: {e}")
            return (True, 0, max_gb)  # Allow upload on error
    
    def _cleanup_old_backups(self, folder_id: str, profile_name: str, max_backups: int):
        """
        Delete oldest backup files if count exceeds max_backups.
        IMPORTANT: This is called AFTER successful upload to ensure safety.
        
        Args:
            folder_id: Google Drive folder ID containing backups
            profile_name: Profile name (for logging)
            max_backups: Maximum number of backups to keep
        """
        if not self.service:
            logging.warning(f"Cannot cleanup backups for '{profile_name}': service not available")
            return
        
        try:
            files = self._list_files_in_folder(folder_id, use_cache=False)
            files_sorted = sorted(
                files,
                key=lambda f: self._parse_drive_timestamp(f.get('modifiedTime', '')) or 0.0,
            )
            
            if len(files_sorted) <= max_backups:
                logging.info(f"Profile '{profile_name}': {len(files_sorted)} backups (within limit of {max_backups})")
                return
            
            # Calculate how many to delete
            files_to_delete = len(files_sorted) - max_backups
            logging.info(f"Profile '{profile_name}': {len(files_sorted)} backups found, deleting {files_to_delete} oldest...")
            
            # Delete oldest files
            for i in range(files_to_delete):
                file_to_delete = files_sorted[i]
                file_id = file_to_delete['id']
                file_name = file_to_delete['name']
                
                try:
                    self.service.files().delete(fileId=file_id).execute()
                    logging.info(f"Deleted old backup: {file_name}")
                except Exception as e:
                    logging.error(f"Failed to delete {file_name}: {e}")
            
            self._invalidate_list_caches(folder_id)
            logging.info(f"Cleanup completed for profile '{profile_name}': kept {max_backups} most recent backups")
            
        except Exception as e:
            logging.error(f"Error during backup cleanup for '{profile_name}': {e}")
            # Don't raise - cleanup failure shouldn't fail the upload


# ===== UI Worker Helpers (for background usage from Qt) =====
class StorageCheckWorker(QObject):
    """
    Qt worker to check storage limit off the UI thread.
    Emits:
        finished(within_limit: bool, current_gb: float, max_gb: int)
        error(message: str)
    """
    finished = Signal(bool, float, int)
    error = Signal(str)

    def __init__(self, provider: Any, max_gb: int):
        super().__init__()
        self.provider = provider
        self.max_gb = int(max_gb)

    def run(self):
        try:
            # Check if provider supports storage limit check
            if hasattr(self.provider, 'check_storage_limit'):
                within_limit, current_gb, max_gb = self.provider.check_storage_limit(self.max_gb)
            else:
                # Provider doesn't support storage check, assume unlimited/ok
                within_limit = True
                current_gb = 0.0
                max_gb = self.max_gb
                
            # Ensure types for signal
            try:
                current_val = float(current_gb)
            except Exception:
                current_val = 0.0
            self.finished.emit(bool(within_limit), current_val, int(max_gb))
        except Exception as e:
            logging.error(f"StorageCheckWorker failed: {e}", exc_info=True)
            self.error.emit(str(e))


# Singleton instance
_drive_manager_instance = None


def get_drive_manager() -> GoogleDriveManager:
    """
    Get the singleton instance of GoogleDriveManager.
    
    Returns:
        GoogleDriveManager: The manager instance
    """
    global _drive_manager_instance
    if _drive_manager_instance is None:
        _drive_manager_instance = GoogleDriveManager()
    return _drive_manager_instance

