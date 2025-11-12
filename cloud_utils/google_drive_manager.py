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
from typing import Optional, List, Dict, Callable, Callable as _Callable
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the token.pickle file
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# App folder name in Google Drive
APP_FOLDER_NAME = "SaveState Backups"


class GoogleDriveManager:
    """
    Manager class for Google Drive operations.
    Handles authentication, upload, download, and sync of backup files.
    """
    
    def __init__(self):
        """Initialize the Google Drive manager."""
        self.service = None
        self.credentials = None
        self.is_connected = False
        self.app_folder_id = None  # ID of the SaveState folder in Google Drive
        
        # Paths for credentials and token
        self.base_dir = Path(__file__).parent
        self.client_secret_file = self.base_dir / 'client_secret.json'
        self.token_file = self.base_dir / 'token.pickle'
        
        # Progress callback
        self.progress_callback: Optional[Callable[[int, int, str], None]] = None
        
        # Settings
        self.compression_level = 'standard'  # 'standard', 'maximum', 'stored'
        self.bandwidth_limit_mbps = None  # None = unlimited

        # Retry/backoff configuration (transient errors)
        self._max_retries = 5
        self._base_backoff_seconds = 0.5
        
    def authenticate(self) -> bool:
        """
        Authenticate with Google Drive using OAuth2.
        
        Returns:
            bool: True if authentication successful, False otherwise
        """
        try:
            creds = None
            
            # Check if we have a saved token
            if self.token_file.exists():
                try:
                    with open(self.token_file, 'rb') as token:
                        creds = pickle.load(token)
                    logging.info("Loaded existing credentials from token file")
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
                        logging.error(f"Client secret file not found: {self.client_secret_file}")
                        return False
                    
                    try:
                        logging.info("Starting OAuth2 flow...")
                        flow = InstalledAppFlow.from_client_secrets_file(
                            str(self.client_secret_file), SCOPES
                        )
                        creds = flow.run_local_server(port=0)
                        logging.info("OAuth2 flow completed successfully")
                    except Exception as e:
                        logging.error(f"Error during OAuth2 flow: {e}")
                        return False
                
                # Save the credentials for the next run
                try:
                    with open(self.token_file, 'wb') as token:
                        pickle.dump(creds, token)
                    logging.info("Credentials saved to token file")
                except Exception as e:
                    logging.warning(f"Error saving token file: {e}")
            
            # Build the service
            try:
                self.service = build('drive', 'v3', credentials=creds)
                self.credentials = creds
                self.is_connected = True
                logging.info("Google Drive service initialized successfully")
                
                # Create or find app folder
                self.app_folder_id = self.create_app_folder()
                if not self.app_folder_id:
                    logging.warning("Could not create/find app folder")
                
                return True
                
            except Exception as e:
                logging.error(f"Error building Drive service: {e}")
                return False
                
        except Exception as e:
            logging.error(f"Unexpected error during authentication: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from Google Drive and clear credentials."""
        self.service = None
        self.credentials = None
        self.is_connected = False
        self.app_folder_id = None
        
        # Optionally delete token file to force re-authentication
        # if self.token_file.exists():
        #     self.token_file.unlink()
        
        logging.info("Disconnected from Google Drive")
    
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
    
    def upload_backup(self, local_path: str, profile_name: str, overwrite: bool = True, 
                      max_backups: Optional[int] = None) -> Dict[str, any]:
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
            
            # Get list of .zip files to upload (sorted by most recent first)
            zip_files = [f for f in os.listdir(local_path) if f.endswith('.zip')]
            if not zip_files:
                logging.warning(f"No .zip files found in {local_path}")
                return {'ok': True, 'uploaded_count': 0, 'skipped_newer_or_same': 0, 'total_candidates': 0}

            # Sort by modification time (newest first)
            try:
                zip_files_sorted = sorted(
                    zip_files,
                    key=lambda name: os.path.getmtime(os.path.join(local_path, name)),
                    reverse=True
                )
            except Exception as e_sort:
                logging.debug(f"Could not sort zip files by mtime: {e_sort}")
                zip_files_sorted = zip_files

            # When a max_backups limit is provided, only upload the N most recent files
            if max_backups and max_backups > 0:
                files_to_upload = zip_files_sorted[:max_backups]
                logging.info(f"Max backups set to {max_backups}. Uploading {len(files_to_upload)} most recent file(s).")
            else:
                files_to_upload = zip_files_sorted
            
            logging.info(f"Uploading {len(files_to_upload)} files for profile '{profile_name}'...")

            uploaded_count = 0
            skipped_newer_or_same = 0
            
            # Upload each file
            for idx, filename in enumerate(files_to_upload, 1):
                file_path = os.path.join(local_path, filename)
                
                # Report progress
                if self.progress_callback:
                    self.progress_callback(idx, len(files_to_upload), f"Uploading {filename}")
                
                # Check if file already exists in Drive
                existing_file_id = None
                if overwrite:
                    existing_file_id = self._find_file_in_folder(filename, profile_folder_id)
                
                if existing_file_id:
                    # Avoid overwriting newer cloud files: compare modified times
                    try:
                        if not self._is_local_newer(file_path, existing_file_id):
                            logging.info(f"Skipping upload for '{filename}': cloud version is newer or same age")
                            skipped_newer_or_same += 1
                            continue
                    except Exception as e_cmp:
                        logging.debug(f"Could not compare modified times for '{filename}': {e_cmp}. Proceeding conservatively with update.")
                    # Update existing file
                    success = self._update_file(existing_file_id, file_path)
                    if success:
                        logging.info(f"Updated file: {filename}")
                        uploaded_count += 1
                    else:
                        logging.warning(f"Failed to update file: {filename}")
                else:
                    # Upload new file
                    success = self._upload_file(file_path, filename, profile_folder_id)
                    if success:
                        logging.info(f"Uploaded file: {filename}")
                        uploaded_count += 1
                    else:
                        logging.warning(f"Failed to upload file: {filename}")
            
            logging.info(f"Upload completed for profile '{profile_name}'")
            
            # IMPORTANT: Cleanup old backups AFTER successful upload (safety first!)
            if max_backups and max_backups > 0:
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
    
    def download_backup(self, profile_name: str, local_path: str, overwrite: bool = True) -> bool:
        """
        Download a backup folder from Google Drive.
        
        Args:
            profile_name: Name of the profile to download
            local_path: Local path where to save the backup
            overwrite: If True, overwrite existing local files; if False, skip existing
            
        Returns:
            bool: True if download successful, False otherwise
        """
        if not self.service or not self.app_folder_id:
            logging.error("Not connected to Google Drive")
            return False
        
        try:
            # Find profile folder in Drive
            profile_folder_id = self._find_folder(profile_name, self.app_folder_id)
            if not profile_folder_id:
                logging.error(f"Profile folder not found in Drive: {profile_name}")
                return False
            
            # Create local directory if it doesn't exist
            os.makedirs(local_path, exist_ok=True)
            
            # List all files in the profile folder
            files = self._list_files_in_folder(profile_folder_id)
            
            if not files:
                logging.warning(f"No files found in cloud folder: {profile_name}")
                return True  # Not an error, just nothing to download
            
            logging.info(f"Downloading {len(files)} files for profile '{profile_name}'...")
            
            # Download each file
            for idx, file_info in enumerate(files, 1):
                file_id = file_info['id']
                filename = file_info['name']
                local_file_path = os.path.join(local_path, filename)
                
                # Report progress
                if self.progress_callback:
                    self.progress_callback(idx, len(files), f"Downloading {filename}")
                
                # Skip if file exists and overwrite is False
                if not overwrite and os.path.exists(local_file_path):
                    logging.info(f"Skipping existing file: {filename}")
                    continue
                
                # Download file
                success = self._download_file(file_id, local_file_path)
                if success:
                    logging.info(f"Downloaded file: {filename}")
                else:
                    logging.warning(f"Failed to download file: {filename}")
            
            logging.info(f"Download completed for profile '{profile_name}'")
            return True
            
        except Exception as e:
            logging.error(f"Error downloading backup: {e}")
            return False
    
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
            return backups
            
        except HttpError as e:
            logging.error(f"HTTP error listing cloud backups: {e}")
            return []
        except Exception as e:
            logging.error(f"Error listing cloud backups: {e}")
            return []
    
    def sync_backup(self, profile_name: str, local_path: str, 
                    direction: str = "bidirectional") -> bool:
        """
        Synchronize a backup between local and cloud.
        
        Args:
            profile_name: Name of the profile to sync
            local_path: Local path to the backup folder
            direction: Sync direction - "upload", "download", or "bidirectional"
            
        Returns:
            bool: True if sync successful, False otherwise
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
            upload_success = self.upload_backup(local_path, profile_name, overwrite=True)
            if not upload_success:
                logging.error("Upload phase of bidirectional sync failed")
                return False
            
            # Then download (without overwriting local files)
            download_success = self.download_backup(profile_name, local_path, overwrite=False)
            if not download_success:
                logging.error("Download phase of bidirectional sync failed")
                return False
            
            logging.info(f"Bidirectional sync completed for profile '{profile_name}'")
            return True
        else:
            logging.error(f"Invalid sync direction: {direction}")
            return False
    
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
    
    def _find_folder(self, folder_name: str, parent_id: str) -> Optional[str]:
        """Find a folder by name in a parent folder."""
        try:
            query = f"name='{folder_name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
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
            query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
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

    def _get_file_modified_time(self, file_id: str) -> Optional[float]:
        """Return the Drive file modified time as epoch seconds (UTC)."""
        try:
            meta = self._execute_with_retries(
                lambda: self.service.files().get(fileId=file_id, fields='modifiedTime').execute(),
                "get file modified time"
            )
            ts = meta.get('modifiedTime')
            if not ts:
                return None
            # Convert RFC3339 to aware datetime
            try:
                dt = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))
            except Exception:
                # Fallback: strip sub-seconds
                if 'T' in ts:
                    main = ts.split('.', 1)[0].replace('Z', '')
                    dt = datetime.datetime.fromisoformat(main + '+00:00')
                else:
                    return None
            return dt.timestamp()
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

    # ===== Retry helpers =====
    def _should_retry_http_error(self, error: HttpError) -> bool:
        try:
            status = int(getattr(error, "status_code", None) or getattr(error.resp, "status", 0))
        except Exception:
            status = 0
        # Retry on common transient statuses
        return status in (408, 429, 500, 502, 503, 504)

    def _sleep_with_backoff(self, attempt: int, context: str):
        delay = self._base_backoff_seconds * (2 ** attempt)
        delay = delay + random.uniform(0, 0.25)  # jitter
        capped = min(delay, 8.0)
        logging.warning(f"Transient error during {context}. Backing off for {capped:.2f}s (attempt {attempt+1}/{self._max_retries})")
        try:
            time.sleep(capped)
        except Exception:
            pass

    def _execute_with_retries(self, func: _Callable[[], any], description: str):
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
            except (OSError, TimeoutError, ConnectionError, BrokenPipeError) as e:  # type: ignore[name-defined]
                self._sleep_with_backoff(attempt, description)
                last_exc = e
                continue
            except Exception as e:
                last_exc = e
                break
        # Exhausted retries or non-retryable
        if last_exc:
            logging.error(f"{description} failed after retries: {last_exc}")
            raise last_exc
    
    def _list_files_in_folder(self, folder_id: str) -> List[Dict]:
        """List all files in a folder."""
        try:
            query = f"'{folder_id}' in parents and trashed=false"
            results = self._execute_with_retries(
                lambda: self.service.files().list(
                    q=query,
                    spaces='drive',
                    fields='files(id, name, size, modifiedTime)',
                    orderBy='name'
                ).execute(),
                "list files in folder"
            )
            
            return results.get('files', [])
            
        except Exception as e:
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
            prev_bytes = 0
            t_prev = time.time()
            attempt = 0
            while response is None:
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
            prev_bytes = 0
            t_prev = time.time()
            attempt = 0
            while response is None:
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
            
            return True
            
        except Exception as e:
            logging.error(f"Error updating file: {e}")
            return False
    
    def _download_file(self, file_id: str, destination_path: str) -> bool:
        """Download a file from Google Drive."""
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

            chunk_size = 1024 * 1024 if self.bandwidth_limit_mbps else None
            downloader = MediaIoBaseDownload(fh, request, chunksize=chunk_size or 1024*1024)
            
            done = False
            prev_bytes = 0
            t_prev = time.time()
            attempt = 0
            while not done:
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
            
            fh.close()
            return True
            
        except Exception as e:
            logging.error(f"Error downloading file: {e}")
            return False
    
    def set_progress_callback(self, callback: Callable[[int, int, str], None]):
        """Set a callback function for progress updates."""
        self.progress_callback = callback
    
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
        try:
            # Get all files in folder, sorted by modification time (oldest first)
            query = f"'{folder_id}' in parents and trashed=false"
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name, modifiedTime)',
                orderBy='modifiedTime'  # Oldest first
            ).execute()
            
            files = results.get('files', [])
            
            if len(files) <= max_backups:
                logging.info(f"Profile '{profile_name}': {len(files)} backups (within limit of {max_backups})")
                return
            
            # Calculate how many to delete
            files_to_delete = len(files) - max_backups
            logging.info(f"Profile '{profile_name}': {len(files)} backups found, deleting {files_to_delete} oldest...")
            
            # Delete oldest files
            for i in range(files_to_delete):
                file_to_delete = files[i]
                file_id = file_to_delete['id']
                file_name = file_to_delete['name']
                
                try:
                    self.service.files().delete(fileId=file_id).execute()
                    logging.info(f"Deleted old backup: {file_name}")
                except Exception as e:
                    logging.error(f"Failed to delete {file_name}: {e}")
            
            logging.info(f"Cleanup completed for profile '{profile_name}': kept {max_backups} most recent backups")
            
        except Exception as e:
            logging.error(f"Error during backup cleanup for '{profile_name}': {e}")
            # Don't raise - cleanup failure shouldn't fail the upload


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

