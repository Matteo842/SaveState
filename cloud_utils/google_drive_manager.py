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
from typing import Optional, List, Dict, Callable
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
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name)'
            ).execute()
            
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
            
            folder = self.service.files().create(
                body=file_metadata,
                fields='id'
            ).execute()
            
            folder_id = folder.get('id')
            logging.info(f"Created new app folder: {folder_id}")
            return folder_id
            
        except HttpError as e:
            logging.error(f"HTTP error creating/finding app folder: {e}")
            return None
        except Exception as e:
            logging.error(f"Error creating/finding app folder: {e}")
            return None
    
    def upload_backup(self, local_path: str, profile_name: str, overwrite: bool = True) -> bool:
        """
        Upload a backup folder to Google Drive.
        
        Args:
            local_path: Local path to the backup folder
            profile_name: Name of the profile (used as folder name in Drive)
            overwrite: If True, overwrite existing files; if False, skip existing
            
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
            
            # Get list of .zip files to upload
            zip_files = [f for f in os.listdir(local_path) if f.endswith('.zip')]
            
            if not zip_files:
                logging.warning(f"No .zip files found in {local_path}")
                return True  # Not an error, just nothing to upload
            
            logging.info(f"Uploading {len(zip_files)} files for profile '{profile_name}'...")
            
            # Upload each file
            for idx, filename in enumerate(zip_files, 1):
                file_path = os.path.join(local_path, filename)
                
                # Report progress
                if self.progress_callback:
                    self.progress_callback(idx, len(zip_files), f"Uploading {filename}")
                
                # Check if file already exists in Drive
                existing_file_id = None
                if overwrite:
                    existing_file_id = self._find_file_in_folder(filename, profile_folder_id)
                
                if existing_file_id:
                    # Update existing file
                    success = self._update_file(existing_file_id, file_path)
                    if success:
                        logging.info(f"Updated file: {filename}")
                    else:
                        logging.warning(f"Failed to update file: {filename}")
                else:
                    # Upload new file
                    success = self._upload_file(file_path, filename, profile_folder_id)
                    if success:
                        logging.info(f"Uploaded file: {filename}")
                    else:
                        logging.warning(f"Failed to upload file: {filename}")
            
            logging.info(f"Upload completed for profile '{profile_name}'")
            return True
            
        except Exception as e:
            logging.error(f"Error uploading backup: {e}")
            return False
    
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
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name, modifiedTime)',
                orderBy='name'
            ).execute()
            
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
            self.service.files().delete(fileId=profile_folder_id).execute()
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
            about = self.service.about().get(fields='storageQuota').execute()
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
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id)'
            ).execute()
            
            items = results.get('files', [])
            return items[0]['id'] if items else None
            
        except Exception as e:
            logging.error(f"Error finding folder '{folder_name}': {e}")
            return None
    
    def _find_file_in_folder(self, filename: str, folder_id: str) -> Optional[str]:
        """Find a file by name in a folder."""
        try:
            query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id)'
            ).execute()
            
            items = results.get('files', [])
            return items[0]['id'] if items else None
            
        except Exception as e:
            logging.error(f"Error finding file '{filename}': {e}")
            return None
    
    def _list_files_in_folder(self, folder_id: str) -> List[Dict]:
        """List all files in a folder."""
        try:
            query = f"'{folder_id}' in parents and trashed=false"
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name, size, modifiedTime)',
                orderBy='name'
            ).execute()
            
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
            
            media = MediaFileUpload(file_path, resumable=True)
            
            request = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            )
            
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    logging.debug(f"Upload progress: {progress}%")
            
            return True
            
        except Exception as e:
            logging.error(f"Error uploading file '{filename}': {e}")
            return False
    
    def _update_file(self, file_id: str, file_path: str) -> bool:
        """Update an existing file in Google Drive."""
        try:
            media = MediaFileUpload(file_path, resumable=True)
            
            request = self.service.files().update(
                fileId=file_id,
                media_body=media
            )
            
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    logging.debug(f"Update progress: {progress}%")
            
            return True
            
        except Exception as e:
            logging.error(f"Error updating file: {e}")
            return False
    
    def _download_file(self, file_id: str, destination_path: str) -> bool:
        """Download a file from Google Drive."""
        try:
            request = self.service.files().get_media(fileId=file_id)
            
            fh = io.FileIO(destination_path, 'wb')
            downloader = MediaIoBaseDownload(fh, request)
            
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    logging.debug(f"Download progress: {progress}%")
            
            fh.close()
            return True
            
        except Exception as e:
            logging.error(f"Error downloading file: {e}")
            return False
    
    def set_progress_callback(self, callback: Callable[[int, int, str], None]):
        """Set a callback function for progress updates."""
        self.progress_callback = callback


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

