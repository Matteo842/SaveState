# cloud_utils/storage_provider.py
# -*- coding: utf-8 -*-
"""
Abstract Storage Provider - Base class for all cloud/network storage providers.
This allows SaveState to support multiple storage backends (Google Drive, SMB, FTP, etc.)
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
import logging


class ProviderType(Enum):
    """Enumeration of supported storage provider types."""
    GOOGLE_DRIVE = "google_drive"
    SMB = "smb"  # Network folder (Windows shares, NAS)
    FTP = "ftp"
    WEBDAV = "webdav"
    GIT = "git"  # Git repository (local + optional remote push/pull)


class StorageProvider(ABC):
    """
    Abstract base class for all storage providers.
    
    Each provider must implement these methods to enable:
    - Connection management
    - Backup upload/download
    - Backup listing and deletion
    - Storage information retrieval
    """
    
    def __init__(self):
        """Initialize common provider attributes."""
        # Progress callbacks for UI feedback
        self.progress_callback: Optional[Callable[[int, int, str], None]] = None
        self.chunk_callback: Optional[Callable[[int, int], None]] = None
        
        # Cancellation support
        self._cancelled = False
        
        # Bandwidth limiting (in Mbps, None = unlimited)
        self.bandwidth_limit_mbps: Optional[float] = None
    
    def set_progress_callback(self, callback: Optional[Callable[[int, int, str], None]]) -> None:
        """Set the progress callback for file-level progress (current, total, message)."""
        self.progress_callback = callback
    
    def set_chunk_callback(self, callback: Optional[Callable[[int, int], None]]) -> None:
        """Set the chunk callback for byte-level progress (current_bytes, total_bytes)."""
        self.chunk_callback = callback
    
    @property
    @abstractmethod
    def provider_type(self) -> ProviderType:
        """Return the provider type enum value."""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return human-readable provider name for UI display."""
        pass
    
    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if currently connected to the storage."""
        pass
    
    @property
    def icon_name(self) -> str:
        """
        Return the icon filename for this provider.
        Override in subclasses if a custom icon is needed.
        """
        return "cloud.png"
    
    # -------------------------------------------------------------------------
    # Connection Management
    # -------------------------------------------------------------------------
    
    @abstractmethod
    def connect(self, **kwargs) -> bool:
        """
        Establish connection to the storage.
        
        Args:
            **kwargs: Provider-specific connection parameters
            
        Returns:
            bool: True if connection successful, False otherwise
        """
        pass
    
    @abstractmethod
    def disconnect(self) -> bool:
        """
        Disconnect from the storage.
        
        Returns:
            bool: True if disconnection successful, False otherwise
        """
        pass
    
    def test_connection(self) -> Dict[str, Any]:
        """
        Test the connection and return status information.
        
        Returns:
            Dict with keys:
                - success: bool
                - message: str (human-readable status)
                - details: Optional[Dict] (provider-specific details)
        """
        try:
            if self.is_connected:
                return {
                    'success': True,
                    'message': f'Connected to {self.name}',
                    'details': None
                }
            else:
                return {
                    'success': False,
                    'message': f'Not connected to {self.name}',
                    'details': None
                }
        except Exception as e:
            logging.error(f"Error testing {self.name} connection: {e}")
            return {
                'success': False,
                'message': str(e),
                'details': None
            }
    
    # -------------------------------------------------------------------------
    # Backup Operations
    # -------------------------------------------------------------------------
    
    @abstractmethod
    def upload_backup(self, local_path: str, profile_name: str, 
                      overwrite: bool = True, 
                      max_backups: Optional[int] = None) -> Dict[str, Any]:
        """
        Upload a backup folder to the storage.
        
        Args:
            local_path: Local path to the backup folder
            profile_name: Name of the profile (used as folder name in storage)
            overwrite: If True, overwrite existing files; if False, skip existing
            max_backups: If set, keep only this many backups (delete oldest)
            
        Returns:
            Dict with keys:
                - ok: bool (True if successful)
                - uploaded_count: int
                - skipped_newer_or_same: int
                - total_candidates: int
                - cancelled: bool (optional)
                - error: str (optional, if failed)
        """
        pass
    
    @abstractmethod
    def download_backup(self, profile_name: str, local_path: str,
                        overwrite: bool = True, 
                        smart_sync: bool = False) -> Dict[str, Any]:
        """
        Download a backup folder from the storage.
        
        Args:
            profile_name: Name of the profile to download
            local_path: Local path where to save the backup
            overwrite: If True, overwrite existing local files
            smart_sync: If True, only overwrite if remote file is newer
            
        Returns:
            Dict with keys:
                - ok: bool
                - downloaded: int
                - skipped: int
                - failed: int
                - total: int
        """
        pass
    
    @abstractmethod
    def list_cloud_backups(self) -> List[Dict[str, Any]]:
        """
        List all backup folders available in the storage.
        
        Returns:
            List of backup info dictionaries with keys:
                - name: str (profile name)
                - file_count: int
                - last_modified: str (ISO format datetime)
                - size: int (total size in bytes)
        """
        pass
    
    @abstractmethod
    def delete_cloud_backup(self, profile_name: str) -> bool:
        """
        Delete a backup folder from the storage.
        
        Args:
            profile_name: Name of the profile to delete
            
        Returns:
            bool: True if deletion successful, False otherwise
        """
        pass
    
    # -------------------------------------------------------------------------
    # Storage Information
    # -------------------------------------------------------------------------
    
    @abstractmethod
    def get_storage_info(self) -> Optional[Dict[str, Any]]:
        """
        Get storage space information.
        
        Returns:
            Optional[Dict] with keys:
                - total: int (total space in bytes)
                - used: int (used space in bytes)
                - free: int (free space in bytes)
                - app_usage: int (bytes used by SaveState backups)
            Returns None if info cannot be retrieved.
        """
        pass
    
    # -------------------------------------------------------------------------
    # Cancellation Support
    # -------------------------------------------------------------------------
    
    def request_cancellation(self) -> None:
        """Request cancellation of current operation."""
        self._cancelled = True
        logging.info(f"{self.name}: Cancellation requested")
    
    def reset_cancellation(self) -> None:
        """Reset cancellation flag (call before starting a new operation)."""
        self._cancelled = False
    
    def is_cancelled(self) -> bool:
        """Check if cancellation was requested."""
        return self._cancelled
    
    # -------------------------------------------------------------------------
    # Configuration
    # -------------------------------------------------------------------------
    
    @abstractmethod
    def get_config(self) -> Dict[str, Any]:
        """
        Get provider configuration for persistence.
        
        Returns:
            Dict containing all configuration needed to restore this provider.
            Should NOT include sensitive data like passwords in plain text.
        """
        pass
    
    @abstractmethod
    def load_config(self, config: Dict[str, Any]) -> bool:
        """
        Load provider configuration from saved settings.
        
        Args:
            config: Configuration dictionary from get_config()
            
        Returns:
            bool: True if configuration loaded successfully
        """
        pass
    
    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """
        Get the configuration schema for this provider.
        Used by the UI to generate configuration forms.
        
        Returns:
            Dict describing required configuration fields:
            {
                'field_name': {
                    'type': 'string' | 'int' | 'bool' | 'password' | 'path',
                    'label': 'Human readable label',
                    'required': bool,
                    'default': any,
                    'help': 'Help text for the field'
                },
                ...
            }
        """
        return {}
