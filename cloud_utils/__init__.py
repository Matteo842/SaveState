# cloud_utils/__init__.py
"""
Cloud Save utilities package.
Contains modules for cloud/network storage integration and backup management.

Supported providers:
- Google Drive (via Google Drive API)
- SMB/Network Folder (native filesystem)
- FTP/FTPS (planned)
- WebDAV (planned)
"""

from cloud_utils.storage_provider import StorageProvider, ProviderType
from cloud_utils.provider_factory import ProviderFactory, register_all_providers

__all__ = [
    'StorageProvider',
    'ProviderType', 
    'ProviderFactory',
    'register_all_providers'
]
