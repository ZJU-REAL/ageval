"""Encrypt org secret values at rest.

HMAC-SHA256 in counter mode, then HMAC-SHA256 over the ciphertext.
``AGEVAL_HOSTED_SECRET_KEY`` is urlsafe-base64 of 32 bytes.
Plaintext is not written to a job row, a profiles file, or an HTTP body.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

from services.registry.errors import RegistryAppError

_NONCE = 16
_TAG = 32


def load_master_key() -> bytes:
    raw = os.environ.get("AGEVAL_HOSTED_SECRET_KEY", "").strip()
    if not raw:
        raise RegistryAppError(
            "hosted_secret_key_missing",
            "AGEVAL_HOSTED_SECRET_KEY is not set",
            http_status=503,
        )
    try:
        key = base64.urlsafe_b64decode(raw)
    except Exception as exc:
        raise RegistryAppError(
            "hosted_secret_key_invalid",
            "AGEVAL_HOSTED_SECRET_KEY must be urlsafe-base64 of 32 bytes",
            http_status=503,
        ) from exc
    if len(key) != 32:
        raise RegistryAppError(
            "hosted_secret_key_invalid",
            "AGEVAL_HOSTED_SECRET_KEY must be urlsafe-base64 of 32 bytes",
            http_status=503,
        )
    return key


def _subkeys(master: bytes) -> tuple[bytes, bytes]:
    enc = hmac.new(master, b"ageval-hosted-enc", hashlib.sha256).digest()
    mac = hmac.new(master, b"ageval-hosted-mac", hashlib.sha256).digest()
    return enc, mac


def _keystream(enc_key: bytes, nonce: bytes, nbytes: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < nbytes:
        block = hmac.new(enc_key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:nbytes])


def encrypt(plaintext: str, *, master: bytes | None = None) -> str:
    key = load_master_key() if master is None else master
    enc, mac = _subkeys(key)
    raw = plaintext.encode("utf-8")
    nonce = secrets.token_bytes(_NONCE)
    stream = _keystream(enc, nonce, len(raw))
    cipher = bytes(a ^ b for a, b in zip(raw, stream, strict=True))
    tag = hmac.new(mac, nonce + cipher, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + tag + cipher).decode("ascii")


def decrypt(token: str, *, master: bytes | None = None) -> str:
    key = load_master_key() if master is None else master
    enc, mac = _subkeys(key)
    try:
        blob = base64.urlsafe_b64decode(token)
    except Exception as exc:
        raise RegistryAppError(
            "hosted_secret_corrupt",
            "secret ciphertext is unreadable",
            http_status=500,
        ) from exc
    if len(blob) < _NONCE + _TAG:
        raise RegistryAppError(
            "hosted_secret_corrupt",
            "secret ciphertext is unreadable",
            http_status=500,
        )
    nonce = blob[:_NONCE]
    tag = blob[_NONCE : _NONCE + _TAG]
    cipher = blob[_NONCE + _TAG :]
    expect = hmac.new(mac, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expect):
        raise RegistryAppError(
            "hosted_secret_corrupt",
            "secret ciphertext failed authentication",
            http_status=500,
        )
    stream = _keystream(enc, nonce, len(cipher))
    raw = bytes(a ^ b for a, b in zip(cipher, stream, strict=True))
    return raw.decode("utf-8")


def scrub(text: str, secrets: list[str], *, limit: int = 2000) -> str:
    """Drop known plaintext from a message that will be stored on the job."""
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, "[redacted]")
    if len(out) > limit:
        return out[:limit]
    return out
