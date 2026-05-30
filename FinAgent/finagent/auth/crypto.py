from __future__ import annotations

import base64
from hashlib import sha256

from .tokens import auth_secret


def _key_bytes() -> bytes:
    return sha256(f"finagent-settings:{auth_secret()}".encode("utf-8")).digest()


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    key = _key_bytes()
    raw = value.encode("utf-8")
    encrypted = bytes(byte ^ key[index % len(key)] for index, byte in enumerate(raw))
    return base64.urlsafe_b64encode(encrypted).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    key = _key_bytes()
    raw = base64.urlsafe_b64decode(value.encode("ascii"))
    decrypted = bytes(byte ^ key[index % len(key)] for index, byte in enumerate(raw))
    return decrypted.decode("utf-8")
