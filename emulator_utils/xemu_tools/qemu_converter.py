
0
# emulator_utils/xemu_tools/qemu_converter.py
# -*- coding: utf-8 -*-

import os
import subprocess
import logging
import tempfile
import shutil
from typing import Optional, Tuple

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

class QEMUConverter:
    """Handles conversion of QCOW2 images to raw format using QEMU tools."""
    
    def __init__(self, qemu_path: str = None):
        """
        Initialize QEMU converter with path to QEMU installation.
        
        Args:
            qemu_path: Path to QEMU installation directory. If None, will try to find QEMU automatically.
        """
        if qemu_path is None:
            qemu_path = self._find_qemu_installation()
        
        self.qemu_path = qemu_path
        if qemu_path:
            # Try both Windows and Linux/Mac executables
            self.qemu_img_path = os.path.join(qemu_path, "qemu-img.exe")
            if not os.path.isfile(self.qemu_img_path):
                self.qemu_img_path = os.path.join(qemu_path, "qemu-img")
        else:
            self.qemu_img_path = None
        
    def _find_qemu_installation(self) -> str:
        """Try to find QEMU installation automatically."""
        # Common QEMU installation paths
        common_paths = [
            r"D:\qemu",  # Default hardcoded path
            r"C:\Program Files\qemu",
            r"C:\qemu",
            "/usr/bin",  # Linux
            "/usr/local/bin",  # macOS/Linux
            "/opt/homebrew/bin"  # macOS with Homebrew
        ]
        
        for path in common_paths:
            if os.path.isdir(path):
                qemu_img = os.path.join(path, "qemu-img.exe")
                if not os.path.isfile(qemu_img):
                    qemu_img = os.path.join(path, "qemu-img")
                
                if os.path.isfile(qemu_img):
                    log.info(f"Found QEMU installation at: {path}")
                    return path
        
        # Try to find qemu-img in PATH
        try:
            import shutil
            qemu_img_path = shutil.which("qemu-img")
            if qemu_img_path:
                qemu_dir = os.path.dirname(qemu_img_path)
                log.info(f"Found QEMU in PATH: {qemu_dir}")
                return qemu_dir
        except Exception:
            pass
        
        log.warning("Could not find QEMU installation automatically")
        return None

    def is_qemu_available(self) -> bool:
        """Check if QEMU tools are available."""
        return self.qemu_img_path and os.path.isfile(self.qemu_img_path)
    
    def convert_qcow2_to_raw(self, qcow2_path: str, output_dir: Optional[str] = None) -> Optional[str]:
        """
        Convert QCOW2 image to raw format.

        Args:
            qcow2_path: Path to QCOW2 file
            output_dir: Optional directory to save the raw image in.

        Returns:
            Path to the raw image file, or None if conversion fails.
        """
        if not os.path.isfile(qcow2_path):
            log.error(f"QCOW2 file not found: {qcow2_path}")
            return None

        if not self.is_qemu_available():
            log.error(f"QEMU tools not found at: {self.qemu_img_path}")
            return None

        # Determine output path - generate unique filename to avoid conflicts
        import uuid
        base_name = os.path.splitext(os.path.basename(qcow2_path))[0]
        unique_id = str(uuid.uuid4())[:8]
        output_filename = f"{base_name}_{unique_id}.raw"
        
        if output_dir:
            output_path = os.path.join(output_dir, output_filename)
        else:
            # Use system temporary directory
            output_path = os.path.join(tempfile.gettempdir(), output_filename)

        try:
            cmd = [
                self.qemu_img_path, "convert", "-f", "qcow2",
                "-O", "raw", qcow2_path, output_path
            ]

            log.info(f"Converting QCOW2 to raw: {' '.join(cmd)}")
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300, check=True
            )

            if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
                log.info(f"Successfully converted QCOW2 to raw: {output_path}")
                return output_path
            else:
                log.error("Conversion completed but output file is invalid.")
                return None

        except subprocess.CalledProcessError as e:
            log.error(f"QEMU conversion failed: {e.stderr.strip()}")
            return None
        except subprocess.TimeoutExpired:
            log.error("QEMU conversion timed out after 5 minutes.")
            return None
        except Exception as e:
            log.error(f"Error during QEMU conversion: {e}")
            return None
    
    def get_image_info(self, qcow2_path: str) -> Tuple[bool, dict]:
        """
        Get information about a QCOW2 image.
        
        Args:
            qcow2_path: Path to QCOW2 file
            
        Returns:
            Tuple of (success, info_dict)
        """
        if not os.path.isfile(qcow2_path):
            return False, {"error": f"QCOW2 file not found: {qcow2_path}"}
            
        if not self.is_qemu_available():
            return False, {"error": f"QEMU tools not found at: {self.qemu_img_path}"}
        
        try:
            cmd = [self.qemu_img_path, "info", "--output=json", qcow2_path]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                import json
                info = json.loads(result.stdout)
                return True, info
            else:
                error_msg = result.stderr.strip() if result.stderr else "Unknown QEMU error"
                return False, {"error": f"Failed to get image info: {error_msg}"}
                
        except Exception as e:
            return False, {"error": f"Error getting image info: {str(e)}"}
    
    def cleanup_raw_image(self, raw_path: str) -> bool:
        """
        Clean up temporary raw image file.
        
        Args:
            raw_path: Path to raw image file
            
        Returns:
            True if cleanup successful
        """
        try:
            if os.path.isfile(raw_path):
                os.remove(raw_path)
                log.info(f"Cleaned up temporary raw image: {raw_path}")
                return True
        except Exception as e:
            log.warning(f"Failed to cleanup raw image {raw_path}: {e}")
        return False

# Global converter instance
_qemu_converter = None

def get_qemu_converter(qemu_path: str = None) -> QEMUConverter:
    """Get global QEMU converter instance."""
    global _qemu_converter
    if _qemu_converter is None:
        _qemu_converter = QEMUConverter(qemu_path)
    return _qemu_converter


def cleanup_temp_xbox_files():
    """
    Clean up any temporary Xbox RAW files that might be left in the system temp directory.
    This should be called when the application exits.
    """
    try:
        temp_dir = tempfile.gettempdir()
        xbox_raw_file = os.path.join(temp_dir, "xbox_hdd.raw")
        
        if os.path.isfile(xbox_raw_file):
            os.remove(xbox_raw_file)
            log.info(f"Cleaned up temporary Xbox RAW file: {xbox_raw_file}")
            
        # Also clean up any xemu_extract_* directories
        import glob
        for temp_extract_dir in glob.glob(os.path.join(temp_dir, "xemu_extract_*")):
            if os.path.isdir(temp_extract_dir):
                shutil.rmtree(temp_extract_dir)
                log.info(f"Cleaned up temporary extract directory: {temp_extract_dir}")
                
    except Exception as e:
        log.warning(f"Error during temp file cleanup: {e}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python qemu_converter.py <qcow2_path> [qemu_path]")
        sys.exit(1)
    
    logging.basicConfig(level=logging.DEBUG)
    
    qcow2_path = sys.argv[1]
    qemu_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    converter = get_qemu_converter(qemu_path)
    
    # Test conversion
    success, result = converter.convert_qcow2_to_raw(qcow2_path)
    if success:
        print(f"Conversion successful: {result}")
        
        # Get image info
        info_success, info = converter.get_image_info(qcow2_path)
        if info_success:
            print("Image info:")
            for key, value in info.items():
                print(f"  {key}: {value}")
    else:
        print(f"Conversion failed: {result}")