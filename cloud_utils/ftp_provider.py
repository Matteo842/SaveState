# cloud_utils/ftp_provider.py
# -*- coding: utf-8 -*-
"""
FTP Provider - Handles backup sync to FTP/FTPS servers.

This provider works with:
- Standard FTP servers
- FTPS (FTP over TLS/SSL)
- Most NAS devices with FTP enabled

Uses Python's built-in ftplib - no external dependencies required.
"""

import os
import logging
import hashlib
import ftplib
import ssl
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from io import BytesIO

from cloud_utils.storage_provider import StorageProvider, ProviderType


class FTPProvider(StorageProvider):
    """
    Storage provider for FTP/FTPS servers.
    
    Uses Python's built-in ftplib for maximum compatibility.
    Supports both plain FTP and FTPS (implicit/explicit TLS).
    """
    
    # Folder name where SaveState stores backups on the FTP server
    APP_FOLDER_NAME = "SaveState_Backups"
    
    def __init__(self):
        """Initialize the FTP provider."""
        super().__init__()
        
        # Configuration
        self._host: Optional[str] = None
        self._port: int = 21
        self._username: str = "anonymous"
        self._password: str = ""
        self._use_tls: bool = False
        self._passive_mode: bool = True
        self._base_path: str = "/"  # Remote base directory
        
        # Connection state
        self._ftp: Optional[ftplib.FTP] = None
        self._connected = False
        
        # Full path to app folder on server
        self._app_folder_path: Optional[str] = None
    
    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.FTP
    
    @property
    def name(self) -> str:
        return "FTP Server"
    
    @property
    def icon_name(self) -> str:
        return "ftp.png"
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to the FTP server."""
        if not self._connected or not self._ftp:
            return False
        
        # Verify connection is still alive
        try:
            self._ftp.voidcmd("NOOP")  # Send NOOP command to check connection
            return True
        except Exception:
            self._connected = False
            return False
    
    @property
    def host(self) -> Optional[str]:
        """Get the configured FTP host."""
        return self._host
    
    # -------------------------------------------------------------------------
    # Connection Management
    # -------------------------------------------------------------------------
    
    def connect(self, host: str = None,
                port: int = None,
                username: str = None,
                password: str = None,
                use_tls: bool = None,
                passive_mode: bool = None,
                base_path: str = None,
                **kwargs) -> bool:
        """
        Connect to the FTP server.
        
        Args:
            host: FTP server hostname or IP
            port: FTP port (default: 21)
            username: FTP username (default: anonymous)
            password: FTP password
            use_tls: Use FTPS (TLS/SSL)
            passive_mode: Use passive mode (recommended for firewalls)
            base_path: Remote base directory
            
        Returns:
            bool: True if connection successful
        """
        # Update configuration if provided
        if host is not None:
            self._host = host
        if port is not None:
            self._port = port
        if username is not None:
            self._username = username
        if password is not None:
            self._password = password
        if use_tls is not None:
            self._use_tls = use_tls
        if passive_mode is not None:
            self._passive_mode = passive_mode
        if base_path is not None:
            self._base_path = base_path or "/"
        
        if not self._host:
            logging.error("FTP Provider: No host configured")
            return False
        
        try:
            # Close existing connection if any
            self.disconnect()
            
            # Create FTP connection
            if self._use_tls:
                # Use FTPS (explicit TLS)
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE  # Allow self-signed certs
                self._ftp = ftplib.FTP_TLS(context=context)
            else:
                self._ftp = ftplib.FTP()
            
            # Set timeout
            self._ftp.timeout = 30
            
            # Connect to server
            logging.info(f"Connecting to FTP: {self._host}:{self._port}")
            self._ftp.connect(self._host, self._port)
            
            # Login
            self._ftp.login(self._username, self._password)
            
            # For FTPS, secure the data connection
            if self._use_tls:
                self._ftp.prot_p()  # Enable data protection
            
            # Set passive/active mode
            if self._passive_mode:
                self._ftp.set_pasv(True)
            else:
                self._ftp.set_pasv(False)
            
            # Switch to binary mode
            self._ftp.voidcmd("TYPE I")
            
            # Navigate to base path
            if self._base_path and self._base_path != "/":
                try:
                    self._ftp.cwd(self._base_path)
                except ftplib.error_perm:
                    logging.warning(f"Base path not found, creating: {self._base_path}")
                    self._mkdirs(self._base_path)
                    self._ftp.cwd(self._base_path)
            
            # Create or verify SaveState folder
            self._app_folder_path = self.APP_FOLDER_NAME
            try:
                self._ftp.cwd(self._app_folder_path)
                self._ftp.cwd("..")  # Go back after checking
            except ftplib.error_perm:
                # Folder doesn't exist, create it
                try:
                    self._ftp.mkd(self._app_folder_path)
                    logging.info(f"Created SaveState folder: {self._app_folder_path}")
                except ftplib.error_perm as e:
                    logging.error(f"Cannot create folder: {e}")
                    return False
            
            self._connected = True
            logging.info(f"FTP Provider connected: {self._host}")
            return True
            
        except ftplib.error_perm as e:
            logging.error(f"FTP permission error: {e}")
            self._connected = False
            return False
        except Exception as e:
            logging.error(f"FTP connection failed: {e}")
            self._connected = False
            return False
    
    def disconnect(self) -> bool:
        """Disconnect from the FTP server."""
        try:
            if self._ftp:
                try:
                    self._ftp.quit()
                except Exception:
                    pass  # Ignore errors on quit
                self._ftp = None
        except Exception:
            pass
        
        self._connected = False
        logging.info("FTP Provider disconnected")
        return True
    
    def test_connection(self) -> Dict[str, Any]:
        """Test the connection and return detailed status."""
        result = {
            'success': False,
            'message': '',
            'details': {
                'host': self._host,
                'port': self._port,
                'tls': self._use_tls,
                'writable': False
            }
        }
        
        if not self._host:
            result['message'] = 'No host configured'
            return result
        
        try:
            # Try to connect if not connected
            if not self.is_connected:
                if not self.connect():
                    result['message'] = 'Connection failed'
                    return result
            
            # Check if we can write (try to create and delete a test file)
            test_filename = '.savestate_test_write'
            test_path = f"{self._app_folder_path}/{test_filename}"
            
            try:
                # Upload empty test file
                self._ftp.cwd(self._app_folder_path)
                self._ftp.storbinary(f"STOR {test_filename}", BytesIO(b"test"))
                self._ftp.delete(test_filename)
                self._ftp.cwd("..")
                result['details']['writable'] = True
            except ftplib.error_perm:
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
        Upload a backup folder to the FTP server.
        
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
            # Navigate to app folder
            self._ftp.cwd(self._app_folder_path)
            
            # Create profile folder
            try:
                self._ftp.mkd(profile_name)
            except ftplib.error_perm:
                pass  # Folder already exists
            
            self._ftp.cwd(profile_name)
            
            # Get existing files on server
            remote_files = {}
            try:
                for entry in self._ftp.mlsd():
                    name, facts = entry
                    if facts.get('type') == 'file':
                        remote_files[name] = {
                            'size': int(facts.get('size', 0)),
                            'modify': facts.get('modify', '')
                        }
            except ftplib.error_perm:
                # MLSD not supported, try NLST
                try:
                    remote_files = {f: {} for f in self._ftp.nlst()}
                except Exception:
                    pass
            
            # Get list of .zip files to upload
            zip_files = [f for f in os.listdir(local_path) if f.endswith('.zip')]
            if not zip_files:
                logging.warning(f"No .zip files found in {local_path}")
                self._ftp.cwd("../..")  # Go back to root
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
                    self._ftp.cwd("../..")
                    return result
                
                local_file = os.path.join(local_path, filename)
                local_size = os.path.getsize(local_file)
                
                # Report progress
                if self.progress_callback:
                    self.progress_callback(idx, len(files_to_upload), f"Uploading {filename}")
                
                # Check if file exists and compare sizes
                if filename in remote_files:
                    remote_info = remote_files[filename]
                    remote_size = remote_info.get('size', 0)
                    
                    if remote_size == local_size:
                        logging.debug(f"Skipping {filename}: same size")
                        result['skipped_newer_or_same'] += 1
                        continue
                    
                    if not overwrite:
                        result['skipped_newer_or_same'] += 1
                        continue
                
                # Upload the file
                try:
                    with open(local_file, 'rb') as f:
                        # Track upload progress
                        uploaded_bytes = [0]
                        
                        def callback(data):
                            uploaded_bytes[0] += len(data)
                            if self.chunk_callback:
                                self.chunk_callback(uploaded_bytes[0], local_size)
                        
                        self._ftp.storbinary(f"STOR {filename}", f, 8192, callback)
                    
                    result['uploaded_count'] += 1
                    logging.debug(f"Uploaded {filename}")
                    
                except Exception as e:
                    logging.error(f"Failed to upload {filename}: {e}")
            
            # Delete old backups if max_backups is set
            if max_backups and max_backups > 0:
                self._cleanup_old_backups_ftp(max_backups)
            
            # Go back to root
            self._ftp.cwd("../..")
            
            result['ok'] = True
            logging.info(f"Upload complete: {result['uploaded_count']} files uploaded")
            return result
            
        except Exception as e:
            logging.error(f"Upload failed: {e}")
            result['error'] = str(e)
            try:
                self._ftp.cwd("/")  # Try to go back to root
            except Exception:
                pass
            return result
    
    def download_backup(self, profile_name: str, local_path: str,
                        overwrite: bool = True,
                        smart_sync: bool = False) -> Dict[str, Any]:
        """
        Download a backup folder from the FTP server.
        
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
            # Navigate to profile folder
            profile_path = f"{self._app_folder_path}/{profile_name}"
            try:
                self._ftp.cwd(profile_path)
            except ftplib.error_perm:
                result['error'] = f'Profile not found: {profile_name}'
                return result
            
            # Create local directory if needed
            os.makedirs(local_path, exist_ok=True)
            
            # Get list of files
            files = []
            try:
                for entry in self._ftp.mlsd():
                    name, facts = entry
                    if facts.get('type') == 'file':
                        files.append({
                            'name': name,
                            'size': int(facts.get('size', 0)),
                            'modify': facts.get('modify', '')
                        })
            except ftplib.error_perm:
                # MLSD not supported, use NLST
                try:
                    files = [{'name': f} for f in self._ftp.nlst()]
                except Exception:
                    pass
            
            result['total'] = len(files)
            
            if not files:
                self._ftp.cwd("../..")
                result['ok'] = True
                return result
            
            # Download each file
            for idx, file_info in enumerate(files, 1):
                filename = file_info['name']
                
                # Check for cancellation
                if self._cancelled:
                    self._ftp.cwd("../..")
                    return result
                
                local_file = os.path.join(local_path, filename)
                
                # Report progress
                if self.progress_callback:
                    self.progress_callback(idx, len(files), f"Downloading {filename}")
                
                # Check if local file exists
                if os.path.exists(local_file):
                    local_size = os.path.getsize(local_file)
                    remote_size = file_info.get('size', 0)
                    
                    if local_size == remote_size:
                        result['skipped'] += 1
                        continue
                    
                    if not overwrite:
                        result['skipped'] += 1
                        continue
                
                # Download the file
                try:
                    remote_size = file_info.get('size', 0)
                    downloaded_bytes = [0]
                    
                    with open(local_file, 'wb') as f:
                        def callback(data):
                            f.write(data)
                            downloaded_bytes[0] += len(data)
                            if self.chunk_callback:
                                self.chunk_callback(downloaded_bytes[0], remote_size)
                        
                        self._ftp.retrbinary(f"RETR {filename}", callback)
                    
                    result['downloaded'] += 1
                    
                except Exception as e:
                    logging.error(f"Failed to download {filename}: {e}")
                    result['failed'] += 1
            
            # Go back to root
            self._ftp.cwd("../..")
            
            result['ok'] = True
            return result
            
        except Exception as e:
            logging.error(f"Download failed: {e}")
            result['error'] = str(e)
            try:
                self._ftp.cwd("/")
            except Exception:
                pass
            return result
    
    def list_cloud_backups(self) -> List[Dict[str, Any]]:
        """List all backup folders on the FTP server."""
        backups = []
        
        if not self.is_connected:
            return backups
        
        try:
            # Navigate to app folder
            self._ftp.cwd(self._app_folder_path)
            
            # List directories
            try:
                for entry in self._ftp.mlsd():
                    name, facts = entry
                    if facts.get('type') == 'dir' and name not in ('.', '..'):
                        # Count files in this directory
                        try:
                            self._ftp.cwd(name)
                            file_count = 0
                            total_size = 0
                            last_modified = None
                            
                            for file_entry in self._ftp.mlsd():
                                fname, ffacts = file_entry
                                if ffacts.get('type') == 'file':
                                    file_count += 1
                                    total_size += int(ffacts.get('size', 0))
                                    
                                    modify = ffacts.get('modify', '')
                                    if modify and (last_modified is None or modify > last_modified):
                                        last_modified = modify
                            
                            self._ftp.cwd('..')
                            
                            # Parse modify time
                            last_mod_iso = None
                            if last_modified:
                                try:
                                    dt = datetime.strptime(last_modified[:14], '%Y%m%d%H%M%S')
                                    last_mod_iso = dt.isoformat()
                                except Exception:
                                    pass
                            
                            backups.append({
                                'name': name,
                                'file_count': file_count,
                                'size': total_size,
                                'last_modified': last_mod_iso
                            })
                            
                        except Exception as e:
                            logging.debug(f"Error reading folder {name}: {e}")
                            try:
                                self._ftp.cwd('..')
                            except Exception:
                                pass
                            
            except ftplib.error_perm:
                # MLSD not supported, use NLST
                try:
                    for name in self._ftp.nlst():
                        if name not in ('.', '..'):
                            backups.append({
                                'name': name,
                                'file_count': 0,
                                'size': 0,
                                'last_modified': None
                            })
                except Exception:
                    pass
            
            # Go back to root
            self._ftp.cwd("..")
            
            return backups
            
        except Exception as e:
            logging.error(f"Failed to list backups: {e}")
            try:
                self._ftp.cwd("/")
            except Exception:
                pass
            return backups
    
    def delete_cloud_backup(self, profile_name: str) -> bool:
        """Delete a backup folder from the FTP server."""
        if not self.is_connected:
            return False
        
        try:
            profile_path = f"{self._app_folder_path}/{profile_name}"
            
            # Navigate to profile folder
            try:
                self._ftp.cwd(profile_path)
            except ftplib.error_perm:
                logging.warning(f"Profile folder not found: {profile_name}")
                return False
            
            # Delete all files in the folder
            try:
                for entry in self._ftp.mlsd():
                    name, facts = entry
                    if facts.get('type') == 'file':
                        self._ftp.delete(name)
            except ftplib.error_perm:
                # MLSD not supported, use NLST
                try:
                    for name in self._ftp.nlst():
                        if name not in ('.', '..'):
                            try:
                                self._ftp.delete(name)
                            except Exception:
                                pass
                except Exception:
                    pass
            
            # Go back and remove the folder
            self._ftp.cwd("..")
            self._ftp.rmd(profile_name)
            
            # Go back to root
            self._ftp.cwd("..")
            
            logging.info(f"Deleted backup folder: {profile_name}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to delete backup: {e}")
            try:
                self._ftp.cwd("/")
            except Exception:
                pass
            return False
    
    # -------------------------------------------------------------------------
    # Storage Information
    # -------------------------------------------------------------------------
    
    def get_storage_info(self) -> Optional[Dict[str, Any]]:
        """
        Get storage space information.
        Note: FTP doesn't have a standard way to get storage info,
        so this may not work on all servers.
        """
        if not self.is_connected:
            return None
        
        try:
            # Try AVBL command (not standard, but supported by some servers)
            try:
                response = self._ftp.sendcmd("AVBL")
                # Parse response like "213 1234567890"
                if response.startswith("213 "):
                    free_bytes = int(response[4:].strip())
                    return {
                        'total': 0,  # Unknown
                        'used': 0,   # Unknown
                        'free': free_bytes,
                        'app_usage': 0  # Would need to calculate
                    }
            except ftplib.error_perm:
                pass
            
            # Storage info not available
            return None
            
        except Exception as e:
            logging.debug(f"Failed to get storage info: {e}")
            return None
    
    # -------------------------------------------------------------------------
    # Configuration
    # -------------------------------------------------------------------------
    
    def get_config(self) -> Dict[str, Any]:
        """Get provider configuration for persistence."""
        return {
            'host': self._host,
            'port': self._port,
            'username': self._username,
            # Note: password is NOT stored here for security
            'use_tls': self._use_tls,
            'passive_mode': self._passive_mode,
            'base_path': self._base_path
        }
    
    def load_config(self, config: Dict[str, Any]) -> bool:
        """Load provider configuration from saved settings."""
        try:
            self._host = config.get('host')
            self._port = config.get('port', 21)
            self._username = config.get('username', 'anonymous')
            self._use_tls = config.get('use_tls', False)
            self._passive_mode = config.get('passive_mode', True)
            self._base_path = config.get('base_path', '/')
            return True
        except Exception as e:
            logging.error(f"Failed to load FTP config: {e}")
            return False
    
    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Get the configuration schema for UI generation."""
        return {
            'host': {
                'type': 'string',
                'label': 'Server Address',
                'required': True,
                'default': '',
                'help': 'FTP server hostname or IP address'
            },
            'port': {
                'type': 'int',
                'label': 'Port',
                'required': False,
                'default': 21,
                'help': 'FTP port (default: 21)'
            },
            'username': {
                'type': 'string',
                'label': 'Username',
                'required': False,
                'default': 'anonymous',
                'help': 'FTP username (leave empty for anonymous)'
            },
            'password': {
                'type': 'password',
                'label': 'Password',
                'required': False,
                'default': '',
                'help': 'FTP password'
            },
            'use_tls': {
                'type': 'bool',
                'label': 'Use FTPS (TLS/SSL)',
                'required': False,
                'default': False,
                'help': 'Enable secure FTP connection'
            },
            'passive_mode': {
                'type': 'bool',
                'label': 'Passive Mode',
                'required': False,
                'default': True,
                'help': 'Use passive mode (recommended for most setups)'
            },
            'base_path': {
                'type': 'string',
                'label': 'Remote Path',
                'required': False,
                'default': '/',
                'help': 'Base directory on the FTP server'
            }
        }
    
    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------
    
    def _mkdirs(self, path: str) -> None:
        """Create directories recursively on FTP server."""
        if not path or path == '/':
            return
        
        parts = path.strip('/').split('/')
        current = ''
        
        for part in parts:
            current = f"{current}/{part}"
            try:
                self._ftp.mkd(current)
            except ftplib.error_perm:
                pass  # Directory already exists
    
    def _cleanup_old_backups_ftp(self, max_backups: int) -> None:
        """Delete old backups exceeding the max_backups limit."""
        try:
            # Get list of files with modification times
            files = []
            for entry in self._ftp.mlsd():
                name, facts = entry
                if facts.get('type') == 'file' and name.endswith('.zip'):
                    files.append({
                        'name': name,
                        'modify': facts.get('modify', '')
                    })
            
            if len(files) <= max_backups:
                return
            
            # Sort by modification time (oldest first)
            files_sorted = sorted(files, key=lambda x: x['modify'])
            
            # Delete oldest files
            files_to_delete = files_sorted[:len(files) - max_backups]
            
            for file_info in files_to_delete:
                try:
                    self._ftp.delete(file_info['name'])
                    logging.info(f"Deleted old backup: {file_info['name']}")
                except Exception as e:
                    logging.warning(f"Failed to delete {file_info['name']}: {e}")
                    
        except Exception as e:
            logging.error(f"Error cleaning up old backups: {e}")
