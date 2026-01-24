# cloud_utils/webdav_provider.py
# -*- coding: utf-8 -*-
"""
WebDAV Provider - Handles backup sync to WebDAV servers.

This provider works with:
- Nextcloud
- ownCloud
- Any WebDAV-compatible server
- Many NAS devices with WebDAV enabled

Uses requests library with standard WebDAV HTTP methods.
"""

import os
import logging
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin, quote

try:
    import requests
    from requests.auth import HTTPBasicAuth, HTTPDigestAuth
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from cloud_utils.storage_provider import StorageProvider, ProviderType


class WebDAVProvider(StorageProvider):
    """
    Storage provider for WebDAV servers (Nextcloud, ownCloud, etc.).
    
    Uses standard WebDAV HTTP methods:
    - PROPFIND: List files/directories
    - MKCOL: Create directory
    - PUT: Upload file
    - GET: Download file
    - DELETE: Delete file/directory
    """
    
    # Folder name where SaveState stores backups
    APP_FOLDER_NAME = "SaveState_Backups"
    
    # WebDAV XML namespace
    DAV_NS = "DAV:"
    
    def __init__(self):
        """Initialize the WebDAV provider."""
        super().__init__()
        
        if not REQUESTS_AVAILABLE:
            logging.warning("requests library not available for WebDAV")
        
        # Configuration
        self._url: Optional[str] = None
        self._username: Optional[str] = None
        self._password: Optional[str] = None
        self._use_digest_auth: bool = False
        self._verify_ssl: bool = True
        
        # Connection state
        self._session: Optional[requests.Session] = None
        self._connected = False
        self._base_url: Optional[str] = None  # Full URL to app folder
        
        # Timeout for requests (seconds)
        self._timeout = 30
    
    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.WEBDAV
    
    @property
    def name(self) -> str:
        return "WebDAV"
    
    @property
    def icon_name(self) -> str:
        return "webdav.png"
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to the WebDAV server."""
        if not self._connected or not self._session:
            return False
        
        # Verify connection with a simple PROPFIND
        try:
            response = self._session.request(
                "PROPFIND",
                self._base_url,
                headers={"Depth": "0"},
                timeout=5
            )
            return response.status_code in (200, 207)
        except Exception:
            self._connected = False
            return False
    
    @property
    def url(self) -> Optional[str]:
        """Get the configured WebDAV URL."""
        return self._url
    
    # -------------------------------------------------------------------------
    # Connection Management
    # -------------------------------------------------------------------------
    
    def connect(self, url: str = None,
                username: str = None,
                password: str = None,
                use_digest_auth: bool = None,
                verify_ssl: bool = None,
                **kwargs) -> bool:
        """
        Connect to the WebDAV server.
        
        Args:
            url: WebDAV server URL (e.g., https://cloud.example.com/remote.php/dav/files/user/)
            username: WebDAV username
            password: WebDAV password or app password
            use_digest_auth: Use Digest auth instead of Basic auth
            verify_ssl: Verify SSL certificates
            
        Returns:
            bool: True if connection successful
        """
        if not REQUESTS_AVAILABLE:
            logging.error("WebDAV Provider: requests library not available")
            return False
        
        # Update configuration if provided
        if url is not None:
            self._url = url.rstrip('/')
        if username is not None:
            self._username = username
        if password is not None:
            self._password = password
        if use_digest_auth is not None:
            self._use_digest_auth = use_digest_auth
        if verify_ssl is not None:
            self._verify_ssl = verify_ssl
        
        if not self._url:
            logging.error("WebDAV Provider: No URL configured")
            return False
        
        try:
            # Close existing session if any
            self.disconnect()
            
            # Create new session
            self._session = requests.Session()
            
            # Set authentication
            if self._username and self._password:
                if self._use_digest_auth:
                    self._session.auth = HTTPDigestAuth(self._username, self._password)
                else:
                    self._session.auth = HTTPBasicAuth(self._username, self._password)
            
            # SSL verification
            self._session.verify = self._verify_ssl
            
            # Test connection with PROPFIND on base URL
            logging.info(f"Connecting to WebDAV: {self._url}")
            response = self._session.request(
                "PROPFIND",
                self._url,
                headers={"Depth": "0"},
                timeout=self._timeout
            )
            
            if response.status_code == 401:
                logging.error("WebDAV Provider: Authentication failed")
                return False
            elif response.status_code not in (200, 207):
                logging.error(f"WebDAV Provider: Server returned {response.status_code}")
                return False
            
            # Create or verify SaveState folder
            self._base_url = f"{self._url}/{self.APP_FOLDER_NAME}"
            
            # Check if folder exists
            response = self._session.request(
                "PROPFIND",
                self._base_url,
                headers={"Depth": "0"},
                timeout=self._timeout
            )
            
            if response.status_code == 404:
                # Create folder
                response = self._session.request(
                    "MKCOL",
                    self._base_url,
                    timeout=self._timeout
                )
                if response.status_code not in (201, 405):  # 405 = already exists
                    logging.error(f"WebDAV Provider: Could not create folder: {response.status_code}")
                    return False
                logging.info(f"Created SaveState folder: {self._base_url}")
            
            self._connected = True
            logging.info(f"WebDAV Provider connected: {self._url}")
            return True
            
        except requests.exceptions.SSLError as e:
            logging.error(f"WebDAV SSL error: {e}")
            self._connected = False
            return False
        except requests.exceptions.ConnectionError as e:
            logging.error(f"WebDAV connection error: {e}")
            self._connected = False
            return False
        except Exception as e:
            logging.error(f"WebDAV connection failed: {e}")
            self._connected = False
            return False
    
    def disconnect(self) -> bool:
        """Disconnect from the WebDAV server."""
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
        
        self._connected = False
        logging.info("WebDAV Provider disconnected")
        return True
    
    def test_connection(self) -> Dict[str, Any]:
        """Test the connection and return detailed status."""
        result = {
            'success': False,
            'message': '',
            'details': {
                'url': self._url,
                'username': self._username,
                'ssl_verify': self._verify_ssl
            }
        }
        
        if not self._url:
            result['message'] = 'No URL configured'
            return result
        
        try:
            if not self.is_connected:
                if not self.connect():
                    result['message'] = 'Connection failed'
                    return result
            
            # Test write access by creating and deleting a test file
            test_url = f"{self._base_url}/.savestate_test"
            
            try:
                # Upload test file
                response = self._session.put(
                    test_url,
                    data=b"test",
                    timeout=self._timeout
                )
                if response.status_code in (200, 201, 204):
                    # Delete test file
                    self._session.delete(test_url, timeout=self._timeout)
                    result['details']['writable'] = True
                else:
                    result['message'] = 'Path is read-only'
                    return result
            except Exception as e:
                result['message'] = f'Write test failed: {e}'
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
        Upload a backup folder to the WebDAV server.
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
            # Create profile folder URL
            profile_url = f"{self._base_url}/{quote(profile_name)}"
            
            # Create folder if it doesn't exist
            response = self._session.request(
                "PROPFIND",
                profile_url,
                headers={"Depth": "0"},
                timeout=self._timeout
            )
            if response.status_code == 404:
                self._session.request("MKCOL", profile_url, timeout=self._timeout)
            
            # Get existing files on server
            remote_files = self._list_directory(profile_url)
            
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
                if self._cancelled:
                    result['cancelled'] = True
                    return result
                
                local_file = os.path.join(local_path, filename)
                local_size = os.path.getsize(local_file)
                file_url = f"{profile_url}/{quote(filename)}"
                
                if self.progress_callback:
                    self.progress_callback(idx, len(files_to_upload), f"Uploading {filename}")
                
                # Check if file exists and compare sizes
                remote_info = remote_files.get(filename)
                if remote_info:
                    remote_size = remote_info.get('size', 0)
                    if remote_size == local_size:
                        logging.debug(f"Skipping {filename}: same size")
                        result['skipped_newer_or_same'] += 1
                        continue
                    
                    if not overwrite:
                        result['skipped_newer_or_same'] += 1
                        continue
                
                # Upload file
                try:
                    with open(local_file, 'rb') as f:
                        response = self._session.put(
                            file_url,
                            data=f,
                            timeout=self._timeout * 10  # Longer timeout for upload
                        )
                    
                    if response.status_code in (200, 201, 204):
                        result['uploaded_count'] += 1
                        logging.debug(f"Uploaded {filename}")
                        
                        if self.chunk_callback:
                            self.chunk_callback(local_size, local_size)
                    else:
                        logging.error(f"Upload failed for {filename}: {response.status_code}")
                        
                except Exception as e:
                    logging.error(f"Failed to upload {filename}: {e}")
            
            # Delete old backups if max_backups is set
            if max_backups and max_backups > 0:
                self._cleanup_old_backups_webdav(profile_url, max_backups)
            
            result['ok'] = True
            logging.info(f"Upload complete: {result['uploaded_count']} files uploaded")
            return result
            
        except Exception as e:
            logging.error(f"Upload failed: {e}")
            result['error'] = str(e)
            return result
    
    def download_backup(self, profile_name: str, local_path: str,
                        overwrite: bool = True,
                        smart_sync: bool = False) -> Dict[str, Any]:
        """
        Download a backup folder from the WebDAV server.
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
            profile_url = f"{self._base_url}/{quote(profile_name)}"
            
            # Check if profile exists
            response = self._session.request(
                "PROPFIND",
                profile_url,
                headers={"Depth": "0"},
                timeout=self._timeout
            )
            if response.status_code == 404:
                result['error'] = f'Profile not found: {profile_name}'
                return result
            
            # Create local directory
            os.makedirs(local_path, exist_ok=True)
            
            # Get list of files
            files = self._list_directory(profile_url)
            result['total'] = len(files)
            
            if not files:
                result['ok'] = True
                return result
            
            # Download each file
            for idx, (filename, file_info) in enumerate(files.items(), 1):
                if self._cancelled:
                    return result
                
                if file_info.get('is_dir'):
                    continue
                
                local_file = os.path.join(local_path, filename)
                file_url = f"{profile_url}/{quote(filename)}"
                
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
                
                # Download file
                try:
                    response = self._session.get(
                        file_url,
                        stream=True,
                        timeout=self._timeout * 10
                    )
                    
                    if response.status_code == 200:
                        with open(local_file, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                f.write(chunk)
                        
                        result['downloaded'] += 1
                        
                        if self.chunk_callback:
                            remote_size = file_info.get('size', 0)
                            self.chunk_callback(remote_size, remote_size)
                    else:
                        logging.error(f"Download failed for {filename}: {response.status_code}")
                        result['failed'] += 1
                        
                except Exception as e:
                    logging.error(f"Failed to download {filename}: {e}")
                    result['failed'] += 1
            
            result['ok'] = True
            return result
            
        except Exception as e:
            logging.error(f"Download failed: {e}")
            result['error'] = str(e)
            return result
    
    def list_cloud_backups(self) -> List[Dict[str, Any]]:
        """List all backup folders on the WebDAV server."""
        backups = []
        
        if not self.is_connected:
            return backups
        
        try:
            # List directories in app folder
            items = self._list_directory(self._base_url)
            
            for name, info in items.items():
                if not info.get('is_dir'):
                    continue
                
                # Get details for this profile
                profile_url = f"{self._base_url}/{quote(name)}"
                files = self._list_directory(profile_url)
                
                file_count = sum(1 for f in files.values() if not f.get('is_dir'))
                total_size = sum(f.get('size', 0) for f in files.values() if not f.get('is_dir'))
                
                # Get last modified
                last_modified = None
                for f in files.values():
                    mod = f.get('modified')
                    if mod and (last_modified is None or mod > last_modified):
                        last_modified = mod
                
                backups.append({
                    'name': name,
                    'file_count': file_count,
                    'size': total_size,
                    'last_modified': last_modified.isoformat() if last_modified else None
                })
            
            return backups
            
        except Exception as e:
            logging.error(f"Failed to list backups: {e}")
            return backups
    
    def delete_cloud_backup(self, profile_name: str) -> bool:
        """Delete a backup folder from the WebDAV server."""
        if not self.is_connected:
            return False
        
        try:
            profile_url = f"{self._base_url}/{quote(profile_name)}"
            
            response = self._session.delete(profile_url, timeout=self._timeout)
            
            if response.status_code in (200, 204):
                logging.info(f"Deleted backup folder: {profile_name}")
                return True
            elif response.status_code == 404:
                logging.warning(f"Profile folder not found: {profile_name}")
                return False
            else:
                logging.error(f"Delete failed: {response.status_code}")
                return False
                
        except Exception as e:
            logging.error(f"Failed to delete backup: {e}")
            return False
    
    # -------------------------------------------------------------------------
    # Storage Information
    # -------------------------------------------------------------------------
    
    def get_storage_info(self) -> Optional[Dict[str, Any]]:
        """
        Get storage space information.
        Note: WebDAV quota support varies by server.
        """
        if not self.is_connected:
            return None
        
        try:
            # Try to get quota using PROPFIND with quota properties
            propfind_body = '''<?xml version="1.0" encoding="utf-8" ?>
            <D:propfind xmlns:D="DAV:">
                <D:prop>
                    <D:quota-available-bytes/>
                    <D:quota-used-bytes/>
                </D:prop>
            </D:propfind>'''
            
            response = self._session.request(
                "PROPFIND",
                self._url,
                headers={
                    "Depth": "0",
                    "Content-Type": "application/xml"
                },
                data=propfind_body,
                timeout=self._timeout
            )
            
            if response.status_code == 207:
                # Parse XML response
                root = ET.fromstring(response.content)
                
                # Find quota elements
                ns = {'D': self.DAV_NS}
                available = root.find('.//D:quota-available-bytes', ns)
                used = root.find('.//D:quota-used-bytes', ns)
                
                if available is not None and used is not None:
                    available_bytes = int(available.text) if available.text else 0
                    used_bytes = int(used.text) if used.text else 0
                    
                    return {
                        'total': available_bytes + used_bytes,
                        'used': used_bytes,
                        'free': available_bytes,
                        'app_usage': 0  # Would need to calculate
                    }
            
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
            'url': self._url,
            'username': self._username,
            # Note: password is NOT stored here for security
            'use_digest_auth': self._use_digest_auth,
            'verify_ssl': self._verify_ssl
        }
    
    def load_config(self, config: Dict[str, Any]) -> bool:
        """Load provider configuration from saved settings."""
        try:
            self._url = config.get('url')
            self._username = config.get('username')
            self._use_digest_auth = config.get('use_digest_auth', False)
            self._verify_ssl = config.get('verify_ssl', True)
            return True
        except Exception as e:
            logging.error(f"Failed to load WebDAV config: {e}")
            return False
    
    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Get the configuration schema for UI generation."""
        return {
            'url': {
                'type': 'string',
                'label': 'WebDAV URL',
                'required': True,
                'default': '',
                'help': 'Full WebDAV URL (e.g., https://cloud.example.com/remote.php/dav/files/username/)'
            },
            'username': {
                'type': 'string',
                'label': 'Username',
                'required': True,
                'default': '',
                'help': 'WebDAV username'
            },
            'password': {
                'type': 'password',
                'label': 'Password',
                'required': True,
                'default': '',
                'help': 'WebDAV password or app password'
            },
            'use_digest_auth': {
                'type': 'bool',
                'label': 'Use Digest Authentication',
                'required': False,
                'default': False,
                'help': 'Use Digest auth instead of Basic auth (rarely needed)'
            },
            'verify_ssl': {
                'type': 'bool',
                'label': 'Verify SSL Certificate',
                'required': False,
                'default': True,
                'help': 'Verify SSL certificates (disable only for self-signed certs)'
            }
        }
    
    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------
    
    def _list_directory(self, url: str) -> Dict[str, Dict[str, Any]]:
        """List contents of a WebDAV directory."""
        files = {}
        
        try:
            response = self._session.request(
                "PROPFIND",
                url,
                headers={"Depth": "1"},
                timeout=self._timeout
            )
            
            if response.status_code != 207:
                return files
            
            # Parse XML response
            root = ET.fromstring(response.content)
            ns = {'D': self.DAV_NS}
            
            for response_elem in root.findall('.//D:response', ns):
                href = response_elem.find('D:href', ns)
                if href is None:
                    continue
                
                href_text = href.text
                # Skip the directory itself
                if href_text.rstrip('/') == url.rstrip('/').split('/')[-1] or \
                   href_text.rstrip('/').endswith(url.rstrip('/').split('/')[-1]):
                    # This might be the directory itself, check if it's the first entry
                    pass
                
                # Get filename from href
                filename = href_text.rstrip('/').split('/')[-1]
                # URL decode the filename
                from urllib.parse import unquote
                filename = unquote(filename)
                
                if not filename or filename == self.APP_FOLDER_NAME:
                    continue
                
                # Check if it's a collection (directory)
                resourcetype = response_elem.find('.//D:resourcetype/D:collection', ns)
                is_dir = resourcetype is not None
                
                # Get size
                size = 0
                size_elem = response_elem.find('.//D:getcontentlength', ns)
                if size_elem is not None and size_elem.text:
                    try:
                        size = int(size_elem.text)
                    except ValueError:
                        pass
                
                # Get last modified
                modified = None
                mod_elem = response_elem.find('.//D:getlastmodified', ns)
                if mod_elem is not None and mod_elem.text:
                    try:
                        # Parse RFC 2822 date
                        from email.utils import parsedate_to_datetime
                        modified = parsedate_to_datetime(mod_elem.text)
                    except Exception:
                        pass
                
                files[filename] = {
                    'is_dir': is_dir,
                    'size': size,
                    'modified': modified
                }
            
        except Exception as e:
            logging.error(f"Error listing directory {url}: {e}")
        
        return files
    
    def _cleanup_old_backups_webdav(self, profile_url: str, max_backups: int) -> None:
        """Delete old backups exceeding the max_backups limit."""
        try:
            files = self._list_directory(profile_url)
            
            # Filter zip files
            zip_files = [(name, info) for name, info in files.items() 
                         if name.endswith('.zip') and not info.get('is_dir')]
            
            if len(zip_files) <= max_backups:
                return
            
            # Sort by modification time (oldest first)
            zip_files_sorted = sorted(
                zip_files,
                key=lambda x: x[1].get('modified') or datetime.min
            )
            
            # Delete oldest files
            files_to_delete = zip_files_sorted[:len(zip_files) - max_backups]
            
            for filename, _ in files_to_delete:
                try:
                    file_url = f"{profile_url}/{quote(filename)}"
                    self._session.delete(file_url, timeout=self._timeout)
                    logging.info(f"Deleted old backup: {filename}")
                except Exception as e:
                    logging.warning(f"Failed to delete {filename}: {e}")
                    
        except Exception as e:
            logging.error(f"Error cleaning up old backups: {e}")
