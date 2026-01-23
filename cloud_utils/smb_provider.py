# cloud_utils/smb_provider.py
# -*- coding: utf-8 -*-
"""
SMB/Network Folder Provider - Handles backup sync to network shares and local folders.

This provider works with:
- Windows UNC paths (\\\\server\\share)
- Mapped network drives (Z:\\backups)
- Local folders (for testing)
- Linux/macOS mounted shares (/mnt/nas/backups)

No external dependencies required - uses native filesystem operations.
"""

import os
import shutil
import logging
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

from cloud_utils.storage_provider import StorageProvider, ProviderType


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
        self._base_path: Optional[str] = None  # Root network path
        self._app_folder_path: Optional[str] = None  # Full path to SaveState folder
        
        # Connection state
        self._connected = False
        
        # Optional credentials (for Windows net use)
        self._use_credentials = False
        self._username: Optional[str] = None
        self._domain: Optional[str] = None
        # Password is NOT stored - should use Windows Credential Manager
    
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
        """Get the configured base network path."""
        return self._base_path
    
    # -------------------------------------------------------------------------
    # Connection Management
    # -------------------------------------------------------------------------
    
    def connect(self, path: str = None, 
                use_credentials: bool = False,
                username: str = None,
                domain: str = None,
                **kwargs) -> bool:
        """
        Connect to the network folder.
        
        Args:
            path: Network path (UNC or mapped drive)
            use_credentials: Whether to use explicit credentials
            username: Username for authentication
            domain: Domain for authentication
            
        Returns:
            bool: True if connection successful
        """
        if path:
            self._base_path = path
        
        if not self._base_path:
            logging.error("SMB Provider: No path configured")
            return False
        
        self._use_credentials = use_credentials
        self._username = username
        self._domain = domain
        
        try:
            # Normalize the path
            base_path = os.path.normpath(self._base_path)
            
            # Check if base path exists
            if not os.path.isdir(base_path):
                logging.error(f"SMB Provider: Path not accessible: {base_path}")
                return False
            
            # Create or verify SaveState folder
            self._app_folder_path = os.path.join(base_path, self.APP_FOLDER_NAME)
            
            if not os.path.exists(self._app_folder_path):
                try:
                    os.makedirs(self._app_folder_path)
                    logging.info(f"Created SaveState folder: {self._app_folder_path}")
                except PermissionError as e:
                    logging.error(f"Cannot create folder (permission denied): {e}")
                    return False
            
            self._connected = True
            logging.info(f"SMB Provider connected: {self._app_folder_path}")
            return True
            
        except Exception as e:
            logging.error(f"SMB Provider connection failed: {e}")
            self._connected = False
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
                'app_folder': self._app_folder_path,
                'writable': False
            }
        }
        
        if not self._base_path:
            result['message'] = 'No path configured'
            return result
        
        try:
            # Check if path exists
            if not os.path.isdir(self._base_path):
                result['message'] = f'Path not accessible: {self._base_path}'
                return result
            
            # Check if we can write
            test_file = os.path.join(self._app_folder_path or self._base_path, 
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
