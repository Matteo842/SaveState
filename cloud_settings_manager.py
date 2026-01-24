# cloud_settings_manager.py
"""
Manager for cloud settings persistence.
Saves/loads cloud_settings.json in the same directory as other settings.
"""

import json
import os
import logging
import settings_manager


CLOUD_SETTINGS_FILENAME = "cloud_settings.json"


def get_cloud_settings_path() -> str:
    """Get the full path to cloud_settings.json in the active config directory."""
    config_dir = settings_manager.get_active_config_dir()
    return os.path.join(config_dir, CLOUD_SETTINGS_FILENAME)


def load_cloud_settings() -> dict:
    """
    Load cloud settings from cloud_settings.json.
    Returns default settings if file doesn't exist.
    """
    default_settings = {
        'auto_sync_on_startup': False,
        'auto_sync_enabled': False,
        'auto_sync_interval_hours': 12,
        'sync_all_profiles': True,
        'bandwidth_limit_enabled': False,
        'bandwidth_limit_mbps': 10,
        'show_sync_notifications': True,
        'max_cloud_backups_enabled': False,
        'max_cloud_backups_count': 5,
        'max_cloud_storage_enabled': False,
        'max_cloud_storage_gb': 5,
        
        # Provider selection (google_drive, smb, ftp, webdav)
        'active_provider': 'google_drive',
        
        # SMB/Network Folder settings
        'smb_enabled': False,
        'smb_path': '',
        'smb_use_credentials': False,
        'smb_username': '',
        'smb_auto_connect': False,
        
        # FTP settings
        'ftp_enabled': False,
        'ftp_host': '',
        'ftp_port': 21,
        'ftp_username': 'anonymous',
        'ftp_base_path': '/',
        'ftp_use_tls': False,
        'ftp_passive_mode': True,
        'ftp_auto_connect': False,
        
        # WebDAV settings
        'webdav_enabled': False,
        'webdav_url': '',
        'webdav_username': '',
        'webdav_verify_ssl': True,
        'webdav_use_digest': False,
        'webdav_auto_connect': False
    }
    
    try:
        settings_path = get_cloud_settings_path()
        
        if not os.path.isfile(settings_path):
            logging.debug(f"Cloud settings file not found, using defaults")
            return default_settings.copy()
        
        with open(settings_path, 'r', encoding='utf-8') as f:
            loaded_settings = json.load(f)
        
        if not isinstance(loaded_settings, dict):
            logging.warning("Cloud settings file is not a dict, using defaults")
            return default_settings.copy()
        
        # Merge with defaults to ensure all keys exist
        merged_settings = default_settings.copy()
        merged_settings.update(loaded_settings)
        
        logging.info("Cloud settings loaded successfully")
        return merged_settings
        
    except Exception as e:
        logging.error(f"Error loading cloud settings: {e}")
        return default_settings.copy()


def save_cloud_settings(settings_dict: dict) -> bool:
    """
    Save cloud settings to cloud_settings.json.
    
    Args:
        settings_dict: Dictionary containing cloud settings
        
    Returns:
        bool: True if save successful, False otherwise
    """
    try:
        if not isinstance(settings_dict, dict):
            logging.error("Cloud settings must be a dictionary")
            return False
        
        config_dir = settings_manager.get_active_config_dir()
        is_portable = settings_manager.is_portable_mode()
        
        # Ensure config directory exists
        try:
            os.makedirs(config_dir, exist_ok=True)
        except Exception as e:
            logging.error(f"Unable to create config directory '{config_dir}': {e}")
            return False
        
        settings_path = os.path.join(config_dir, CLOUD_SETTINGS_FILENAME)
        
        # Save settings
        with open(settings_path, 'w', encoding='utf-8') as f:
            json.dump(settings_dict, f, indent=4)
        
        logging.info("Cloud settings saved successfully")
        
        # Mirror to backup directory if NOT in portable mode
        # (In portable mode, config_dir IS already the backup directory)
        if not is_portable:
            try:
                # Get backup directory from main settings
                main_settings, _ = settings_manager.load_settings()
                backup_root = main_settings.get("backup_base_dir")
                
                if backup_root:
                    mirror_dir = os.path.join(backup_root, ".savestate")
                    os.makedirs(mirror_dir, exist_ok=True)
                    mirror_path = os.path.join(mirror_dir, CLOUD_SETTINGS_FILENAME)
                    
                    with open(mirror_path, 'w', encoding='utf-8') as mf:
                        json.dump(settings_dict, mf, indent=4)
                    
                    logging.debug(f"Cloud settings mirrored to backup: {mirror_path}")
            except Exception as e_mirror:
                logging.warning(f"Unable to mirror cloud settings to backup root: {e_mirror}")
        
        return True
        
    except Exception as e:
        logging.error(f"Error saving cloud settings: {e}")
        return False


def delete_cloud_settings() -> bool:
    """
    Delete cloud_settings.json file.
    
    Returns:
        bool: True if deletion successful or file doesn't exist, False on error
    """
    try:
        settings_path = get_cloud_settings_path()
        
        if os.path.isfile(settings_path):
            os.remove(settings_path)
            logging.info(f"Cloud settings deleted: {settings_path}")
        
        return True
        
    except Exception as e:
        logging.error(f"Error deleting cloud settings: {e}")
        return False
