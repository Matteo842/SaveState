# emulator_utils/obfuscation_utils.py
KEY = b's3cr3t_k3y'

def xor_bytes(data: bytes) -> bytes:
    return bytes(b ^ KEY[i % len(KEY)] for i, b in enumerate(data))
