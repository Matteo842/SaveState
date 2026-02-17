# cloud_utils/git_provider.py
# -*- coding: utf-8 -*-
"""
Git Provider - Handles backup sync to Git repositories.

This provider works with:
- Local Git repositories
- GitHub, GitLab, Bitbucket, or any Git remote
- Any Git-compatible hosting service

Uses subprocess to run git commands - no external Python dependencies required.
Requires Git to be installed on the system.
"""

import os
import shutil
import logging
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

from cloud_utils.storage_provider import StorageProvider, ProviderType


class GitProvider(StorageProvider):
    """
    Storage provider for Git repositories.
    
    Stores backups in a local Git repo under SaveState_Backups/ folder.
    Supports optional push/pull to remote (GitHub, GitLab, etc.).
    """
    
    # Folder name where SaveState stores backups in the repo
    APP_FOLDER_NAME = "SaveState_Backups"
    
    def __init__(self):
        """Initialize the Git provider."""
        super().__init__()
        
        # Configuration
        self._repo_path: Optional[str] = None
        self._remote_url: Optional[str] = None
        self._branch: str = "main"
        self._auto_push: bool = True
        self._auto_pull: bool = True
        
        # Connection state
        self._connected = False
        self._backup_root: Optional[Path] = None
    
    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.GIT
    
    @property
    def name(self) -> str:
        return "Git Repository"
    
    @property
    def icon_name(self) -> str:
        return "git.png"
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to the Git repository."""
        return self._connected and self._backup_root is not None
    
    @property
    def repo_path(self) -> Optional[str]:
        """Get the configured repository path."""
        return self._repo_path
    
    # -------------------------------------------------------------------------
    # Git Helpers
    # -------------------------------------------------------------------------
    
    def _run_git(self, *args: str, cwd: Optional[str] = None) -> tuple[bool, str]:
        """
        Run a git command.
        
        Returns:
            (success, output_or_error)
        """
        cwd = cwd or self._repo_path
        if not cwd:
            return False, "No repository path"
        
        try:
            run_kwargs = dict(
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=120
            )
            if os.name == "nt":
                run_kwargs["creationflags"] = getattr(
                    subprocess, "CREATE_NO_WINDOW", 0
                )
            result = subprocess.run(["git"] + list(args), **run_kwargs)
            output = (result.stdout + result.stderr).strip()
            return result.returncode == 0, output
        except FileNotFoundError:
            return False, "Git is not installed or not in PATH"
        except subprocess.TimeoutExpired:
            return False, "Git command timed out"
        except Exception as e:
            return False, str(e)
    
    def _git_available(self) -> bool:
        """Check if Git is available on the system."""
        # Use tempdir instead of cwd to avoid issues with compiled apps
        # (Nuitka/PyInstaller may run from temp directories that get deleted)
        ok, _ = self._run_git("--version", cwd=tempfile.gettempdir())
        return ok
    
    # -------------------------------------------------------------------------
    # Connection Management
    # -------------------------------------------------------------------------
    
    def connect(self, repo_path: str = None,
                remote_url: str = None,
                branch: str = None,
                auto_push: bool = None,
                auto_pull: bool = None,
                **kwargs) -> bool:
        """
        Connect to the Git repository.
        
        Args:
            repo_path: Path to the local Git repository
            remote_url: Optional remote URL for push/pull
            branch: Branch to use (default: main)
            auto_push: Push to remote after uploads
            auto_pull: Pull from remote before operations
            
        Returns:
            bool: True if connection successful
        """
        if not self._git_available():
            logging.error("Git Provider: Git is not installed or not in PATH")
            return False
        
        # Update configuration if provided
        if repo_path is not None:
            self._repo_path = repo_path
        if remote_url is not None:
            self._remote_url = remote_url
        if branch is not None:
            self._branch = branch or "main"
        if auto_push is not None:
            self._auto_push = auto_push
        if auto_pull is not None:
            self._auto_pull = auto_pull
        
        if not self._repo_path:
            logging.error("Git Provider: No repository path configured")
            return False
        
        repo_path = os.path.abspath(os.path.expanduser(self._repo_path))
        
        try:
            self.disconnect()
            
            # Ensure directory exists
            if not os.path.isdir(repo_path):
                os.makedirs(repo_path, exist_ok=True)
            
            git_dir = os.path.join(repo_path, ".git")
            if not os.path.isdir(git_dir):
                # Init new repo
                ok, out = self._run_git("init", cwd=repo_path)
                if not ok:
                    logging.error(f"Git init failed: {out}")
                    return False
                logging.info(f"Initialized new Git repo: {repo_path}")
                
                # Create initial branch if needed
                self._run_git("checkout", "-b", self._branch, cwd=repo_path)
                
                # Add remote if URL provided
                if self._remote_url:
                    self._run_git("remote", "add", "origin", self._remote_url, cwd=repo_path)
            
            # Ensure backup folder exists
            backup_root = Path(repo_path) / self.APP_FOLDER_NAME
            backup_root.mkdir(parents=True, exist_ok=True)
            
            # Add .gitignore to exclude temp files if not present
            gitignore = backup_root / ".gitignore"
            if not gitignore.exists():
                gitignore.write_text("# SaveState backup folder\n", encoding="utf-8")
            
            self._backup_root = backup_root
            self._connected = True
            logging.info(f"Git Provider connected: {repo_path}")
            return True
            
        except Exception as e:
            logging.error(f"Git connection failed: {e}")
            self._connected = False
            return False
    
    def disconnect(self) -> bool:
        """Disconnect from the Git repository."""
        self._backup_root = None
        self._connected = False
        logging.info("Git Provider disconnected")
        return True
    
    def test_connection(self) -> Dict[str, Any]:
        """Test the connection and return detailed status."""
        result = {
            'success': False,
            'message': '',
            'details': {
                'repo_path': self._repo_path,
                'branch': self._branch,
                'remote': self._remote_url,
                'writable': False
            }
        }
        
        if not self._repo_path:
            result['message'] = 'No repository path configured'
            return result
        
        if not self._git_available():
            result['message'] = 'Git is not installed or not in PATH'
            return result
        
        try:
            if not self.is_connected:
                if not self.connect():
                    result['message'] = 'Connection failed'
                    return result
            
            # Test write by creating and removing a test file
            test_file = self._backup_root / ".savestate_test"
            try:
                test_file.write_text("test", encoding="utf-8")
                test_file.unlink()
                result['details']['writable'] = True
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
    
    def _pull_if_needed(self) -> bool:
        """Pull from remote if configured and auto_pull is enabled.
        
        Returns:
            True if pull succeeded or was skipped, False on real failure.
        """
        if not self._auto_pull or not self._remote_url:
            return True
        
        ok, out = self._run_git("pull", "origin", self._branch, "--rebase")
        if not ok:
            out_lower = out.lower()
            # These are expected on first push or empty remote - not real errors
            if ("couldn't find remote ref" in out_lower
                    or "no such ref" in out_lower
                    or "does not appear to be a git repository" not in out_lower):
                logging.info(f"Git pull skipped (remote may not exist yet): {out}")
                return True
            # Real failure (auth error, network issue, merge conflict, etc.)
            logging.error(f"Git pull failed: {out}")
            return False
        return True
    
    def _push_if_needed(self, commit_msg: str = "SaveState backup") -> bool:
        """Push to remote if configured and auto_push is enabled."""
        if not self._auto_push or not self._remote_url:
            return True
        
        ok, out = self._run_git("push", "origin", self._branch)
        if not ok:
            logging.warning(f"Git push failed: {out}")
        return ok
    
    def upload_backup(self, local_path: str, profile_name: str,
                      overwrite: bool = True,
                      max_backups: Optional[int] = None) -> Dict[str, Any]:
        """
        Upload a backup folder to the Git repository.
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
            # Pull latest first
            self._pull_if_needed()
            
            profile_dir = self._backup_root / profile_name
            profile_dir.mkdir(parents=True, exist_ok=True)
            
            # Get existing files
            existing = {f.name: f.stat().st_size for f in profile_dir.iterdir() if f.is_file()}
            
            # Get .zip files to upload
            zip_files = [f for f in os.listdir(local_path) if f.endswith('.zip')]
            if not zip_files:
                logging.warning(f"No .zip files found in {local_path}")
                result['ok'] = True
                return result
            
            # Sort by mtime, newest first
            try:
                zip_files_sorted = sorted(
                    zip_files,
                    key=lambda n: os.path.getmtime(os.path.join(local_path, n)),
                    reverse=True
                )
            except Exception:
                zip_files_sorted = zip_files
            
            if max_backups and max_backups > 0:
                files_to_upload = zip_files_sorted[:max_backups]
            else:
                files_to_upload = zip_files_sorted
            
            result['total_candidates'] = len(files_to_upload)
            
            changed = False
            for idx, filename in enumerate(files_to_upload, 1):
                if self._cancelled:
                    result['cancelled'] = True
                    return result
                
                local_file = os.path.join(local_path, filename)
                local_size = os.path.getsize(local_file)
                dest_file = profile_dir / filename
                
                if self.progress_callback:
                    self.progress_callback(idx, len(files_to_upload), f"Uploading {filename}")
                
                if filename in existing:
                    if existing[filename] == local_size:
                        result['skipped_newer_or_same'] += 1
                        continue
                    if not overwrite:
                        result['skipped_newer_or_same'] += 1
                        continue
                
                shutil.copy2(local_file, dest_file)
                result['uploaded_count'] += 1
                changed = True
                
                if self.chunk_callback:
                    self.chunk_callback(local_size, local_size)
            
            # Cleanup old backups
            if max_backups and max_backups > 0:
                zip_in_dir = [f for f in profile_dir.iterdir() if f.is_file() and f.suffix == '.zip']
                if len(zip_in_dir) > max_backups:
                    by_mtime = sorted(zip_in_dir, key=lambda f: f.stat().st_mtime)
                    for f in by_mtime[:-max_backups]:
                        f.unlink()
                        changed = True
            
            if changed:
                # Git add and commit
                # Resolve both paths to handle Windows case-insensitivity
                # (e.g. D:\repo vs d:\repo would break relative_to)
                resolved_profile = Path(profile_dir).resolve()
                resolved_repo = Path(self._repo_path).resolve()
                relative_path = str(resolved_profile.relative_to(resolved_repo))
                self._run_git("add", relative_path)
                self._run_git("commit", "-m", f"SaveState: sync {profile_name}")
                self._push_if_needed()
            
            result['ok'] = True
            logging.info(f"Git upload complete: {result['uploaded_count']} files")
            return result
            
        except Exception as e:
            logging.error(f"Git upload failed: {e}")
            result['error'] = str(e)
            return result
    
    def download_backup(self, profile_name: str, local_path: str,
                        overwrite: bool = True,
                        smart_sync: bool = False) -> Dict[str, Any]:
        """
        Download a backup folder from the Git repository.
        
        Args:
            profile_name: Name of the profile to download
            local_path: Local path where to save the backup
            overwrite: If True, overwrite existing local files
            smart_sync: If True, only overwrite if remote file is newer
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
            self._pull_if_needed()
            
            profile_dir = self._backup_root / profile_name
            if not profile_dir.is_dir():
                result['error'] = f'Profile not found: {profile_name}'
                return result
            
            os.makedirs(local_path, exist_ok=True)
            files = [f for f in profile_dir.iterdir() if f.is_file() and f.suffix == '.zip']
            result['total'] = len(files)
            
            for idx, src_file in enumerate(files, 1):
                if self._cancelled:
                    return result
                
                filename = src_file.name
                dest_file = os.path.join(local_path, filename)
                
                if self.progress_callback:
                    self.progress_callback(idx, len(files), f"Downloading {filename}")
                
                if os.path.exists(dest_file):
                    local_size = os.path.getsize(dest_file)
                    remote_stat = src_file.stat()
                    remote_size = remote_stat.st_size
                    
                    if smart_sync:
                        # Only overwrite if remote is newer (by mtime)
                        local_mtime = os.path.getmtime(dest_file)
                        if remote_stat.st_mtime <= local_mtime:
                            result['skipped'] += 1
                            continue
                    elif local_size == remote_size:
                        # Default: skip if same size
                        result['skipped'] += 1
                        continue
                    
                    if not overwrite and not smart_sync:
                        result['skipped'] += 1
                        continue
                
                try:
                    shutil.copy2(src_file, dest_file)
                    result['downloaded'] += 1
                    if self.chunk_callback:
                        size = src_file.stat().st_size
                        self.chunk_callback(size, size)
                except Exception as e:
                    logging.error(f"Failed to copy {filename}: {e}")
                    result['failed'] += 1
            
            result['ok'] = True
            return result
            
        except Exception as e:
            logging.error(f"Git download failed: {e}")
            result['error'] = str(e)
            return result
    
    def list_cloud_backups(self) -> List[Dict[str, Any]]:
        """List all backup folders in the Git repository."""
        backups = []
        
        if not self.is_connected:
            return backups
        
        try:
            self._pull_if_needed()
            
            for item in self._backup_root.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    files = list(item.glob("*.zip"))
                    total_size = sum(f.stat().st_size for f in files)
                    last_mod = None
                    for f in files:
                        m = datetime.fromtimestamp(f.stat().st_mtime)
                        if last_mod is None or m > last_mod:
                            last_mod = m
                    
                    backups.append({
                        'name': item.name,
                        'file_count': len(files),
                        'size': total_size,
                        'last_modified': last_mod.isoformat() if last_mod else None
                    })
            
            return backups
            
        except Exception as e:
            logging.error(f"Failed to list backups: {e}")
            return backups
    
    def delete_cloud_backup(self, profile_name: str) -> bool:
        """Delete a backup folder from the Git repository."""
        if not self.is_connected:
            return False
        
        try:
            profile_dir = self._backup_root / profile_name
            if not profile_dir.is_dir():
                logging.warning(f"Profile folder not found: {profile_name}")
                return False
            
            shutil.rmtree(profile_dir)
            self._run_git("add", "-A", cwd=str(self._backup_root))
            self._run_git("commit", "-m", f"SaveState: remove {profile_name}")
            self._push_if_needed()
            logging.info(f"Deleted backup folder: {profile_name}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to delete backup: {e}")
            return False
    
    # -------------------------------------------------------------------------
    # Storage Information
    # -------------------------------------------------------------------------
    
    def get_storage_info(self) -> Optional[Dict[str, Any]]:
        """
        Get storage space information for the backup folder.
        """
        if not self.is_connected:
            return None
        
        try:
            total_size = 0
            for f in self._backup_root.rglob("*"):
                if f.is_file():
                    total_size += f.stat().st_size
            
            # Git doesn't have quota - return app usage only
            return {
                'total': 0,
                'used': 0,
                'free': 0,
                'app_usage': total_size
            }
        except Exception as e:
            logging.debug(f"Failed to get storage info: {e}")
            return None
    
    # -------------------------------------------------------------------------
    # Configuration
    # -------------------------------------------------------------------------
    
    def get_config(self) -> Dict[str, Any]:
        """Get provider configuration for persistence."""
        return {
            'repo_path': self._repo_path,
            'remote_url': self._remote_url,
            'branch': self._branch,
            'auto_push': self._auto_push,
            'auto_pull': self._auto_pull
        }
    
    def load_config(self, config: Dict[str, Any]) -> bool:
        """Load provider configuration from saved settings."""
        try:
            self._repo_path = config.get('repo_path')
            self._remote_url = config.get('remote_url')
            self._branch = config.get('branch', 'main')
            self._auto_push = config.get('auto_push', True)
            self._auto_pull = config.get('auto_pull', True)
            return True
        except Exception as e:
            logging.error(f"Failed to load Git config: {e}")
            return False
    
    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Get the configuration schema for UI generation."""
        return {
            'repo_path': {
                'type': 'path',
                'label': 'Repository Path',
                'required': True,
                'default': '',
                'help': 'Path to the local Git repository (created if it does not exist)'
            },
            'remote_url': {
                'type': 'string',
                'label': 'Remote URL',
                'required': False,
                'default': '',
                'help': 'Git remote URL for push/pull (GitHub, GitLab, etc.)'
            },
            'branch': {
                'type': 'string',
                'label': 'Branch',
                'required': False,
                'default': 'main',
                'help': 'Branch to use for backups'
            },
            'auto_push': {
                'type': 'bool',
                'label': 'Auto-push after upload',
                'required': False,
                'default': True,
                'help': 'Automatically push to remote after uploading backups'
            },
            'auto_pull': {
                'type': 'bool',
                'label': 'Auto-pull before operations',
                'required': False,
                'default': True,
                'help': 'Pull from remote before upload/download'
            }
        }
