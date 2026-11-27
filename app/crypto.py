import os
from pathlib import Path
from cryptography.fernet import Fernet

KEY_DIR = Path(os.environ.get("JMON_HOME", Path.home() / ".juniper_monitor"))
KEY_FILE = KEY_DIR / "secret.key"


def _load_or_create_key() -> bytes:
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    KEY_FILE.write_bytes(key)
    KEY_FILE.chmod(0o600)
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()
