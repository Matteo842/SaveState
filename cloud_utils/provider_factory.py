# cloud_utils/provider_factory.py
# -*- coding: utf-8 -*-
"""
Provider Factory - Creates and manages storage provider instances.
Provides a registry of available providers and handles provider lifecycle.
"""

import logging
from typing import Dict, List, Optional, Type, Any

from cloud_utils.storage_provider import StorageProvider, ProviderType


class ProviderFactory:
    """
    Factory class for creating and managing storage providers.
    
    This class maintains a registry of available provider types and
    creates provider instances on demand.
    """
    
    # Registry of provider classes
    _provider_registry: Dict[ProviderType, Type[StorageProvider]] = {}
    
    # Singleton instances of active providers
    _active_providers: Dict[ProviderType, StorageProvider] = {}
    
    @classmethod
    def register_provider(cls, provider_type: ProviderType, 
                          provider_class: Type[StorageProvider]) -> None:
        """
        Register a provider class in the factory.
        
        Args:
            provider_type: The ProviderType enum value
            provider_class: The provider class (not instance)
        """
        cls._provider_registry[provider_type] = provider_class
        logging.debug(f"Registered provider: {provider_type.value}")
    
    @classmethod
    def get_provider(cls, provider_type: ProviderType, 
                     create_new: bool = False) -> Optional[StorageProvider]:
        """
        Get a provider instance.
        
        Args:
            provider_type: The type of provider to get
            create_new: If True, create a new instance instead of reusing existing
            
        Returns:
            StorageProvider instance or None if provider not registered
        """
        # Check if we have an active instance
        if not create_new and provider_type in cls._active_providers:
            return cls._active_providers[provider_type]
        
        # Check if provider is registered
        if provider_type not in cls._provider_registry:
            logging.error(f"Provider not registered: {provider_type.value}")
            return None
        
        # Create new instance
        try:
            provider_class = cls._provider_registry[provider_type]
            provider = provider_class()
            
            # Cache the instance
            cls._active_providers[provider_type] = provider
            logging.info(f"Created provider instance: {provider_type.value}")
            
            return provider
        except Exception as e:
            logging.error(f"Failed to create provider {provider_type.value}: {e}")
            return None
    
    @classmethod
    def get_available_providers(cls) -> List[Dict[str, Any]]:
        """
        Get list of all registered providers with their metadata.
        
        Returns:
            List of dicts with provider info:
                - type: ProviderType enum value
                - type_str: String representation of type
                - name: Human-readable name
                - icon: Icon filename
                - connected: Whether currently connected
        """
        providers = []
        
        for provider_type in cls._provider_registry:
            try:
                provider = cls.get_provider(provider_type)
                if provider:
                    providers.append({
                        'type': provider_type,
                        'type_str': provider_type.value,
                        'name': provider.name,
                        'icon': provider.icon_name,
                        'connected': provider.is_connected
                    })
            except Exception as e:
                logging.warning(f"Error getting provider info for {provider_type}: {e}")
        
        return providers
    
    @classmethod
    def get_connected_providers(cls) -> List[StorageProvider]:
        """
        Get list of all currently connected providers.
        
        Returns:
            List of connected StorageProvider instances
        """
        connected = []
        for provider in cls._active_providers.values():
            if provider.is_connected:
                connected.append(provider)
        return connected
    
    @classmethod
    def disconnect_all(cls) -> None:
        """Disconnect all active providers."""
        for provider_type, provider in cls._active_providers.items():
            try:
                if provider.is_connected:
                    provider.disconnect()
                    logging.info(f"Disconnected provider: {provider_type.value}")
            except Exception as e:
                logging.error(f"Error disconnecting {provider_type.value}: {e}")
    
    @classmethod
    def cleanup(cls) -> None:
        """
        Clean up all providers (disconnect and clear cache).
        Call this when the application is closing.
        """
        cls.disconnect_all()
        cls._active_providers.clear()
        logging.info("Provider factory cleaned up")
    
    @classmethod
    def is_provider_available(cls, provider_type: ProviderType) -> bool:
        """Check if a provider type is registered and available."""
        return provider_type in cls._provider_registry
    
    @classmethod
    def get_provider_by_string(cls, type_string: str) -> Optional[StorageProvider]:
        """
        Get a provider by its string type name.
        
        Args:
            type_string: String like "google_drive", "smb", "ftp"
            
        Returns:
            StorageProvider instance or None
        """
        try:
            provider_type = ProviderType(type_string)
            return cls.get_provider(provider_type)
        except ValueError:
            logging.error(f"Unknown provider type: {type_string}")
            return None


def register_all_providers() -> None:
    """
    Register all available providers.
    Call this once at application startup.
    """
    # Import providers here to avoid circular imports
    try:
        from cloud_utils.google_drive_manager import GoogleDriveManager
        ProviderFactory.register_provider(ProviderType.GOOGLE_DRIVE, GoogleDriveManager)
    except ImportError as e:
        logging.warning(f"Could not import GoogleDriveManager: {e}")
    
    # SMB Provider (will be added)
    try:
        from cloud_utils.smb_provider import SMBProvider
        ProviderFactory.register_provider(ProviderType.SMB, SMBProvider)
    except ImportError:
        logging.debug("SMB provider not yet implemented")
    
    # FTP Provider (will be added later)
    try:
        from cloud_utils.ftp_provider import FTPProvider
        ProviderFactory.register_provider(ProviderType.FTP, FTPProvider)
    except ImportError:
        logging.debug("FTP provider not yet implemented")
    
    # WebDAV Provider (will be added later)
    try:
        from cloud_utils.webdav_provider import WebDAVProvider
        ProviderFactory.register_provider(ProviderType.WEBDAV, WebDAVProvider)
    except ImportError:
        logging.debug("WebDAV provider not yet implemented")
    
    # Git Provider
    try:
        from cloud_utils.git_provider import GitProvider
        ProviderFactory.register_provider(ProviderType.GIT, GitProvider)
    except ImportError as e:
        logging.debug(f"Git provider not available: {e}")
    
    logging.info(f"Registered {len(ProviderFactory._provider_registry)} storage providers")
