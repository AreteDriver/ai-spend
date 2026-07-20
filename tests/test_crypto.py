"""Tests for ai_spend.crypto."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from ai_spend.crypto import decrypt, encrypt, get_or_create_key


class TestKeyManagement:
    def test_get_or_create_key_generates(self, tmp_path: Path):
        key = get_or_create_key(tmp_path)
        assert isinstance(key, bytes)
        assert len(key) > 0
        key_path = tmp_path / ".key"
        assert key_path.exists()

    def test_get_or_create_key_reads_existing(self, tmp_path: Path):
        key1 = get_or_create_key(tmp_path)
        key2 = get_or_create_key(tmp_path)
        assert key1 == key2

    def test_key_file_permissions(self, tmp_path: Path):
        get_or_create_key(tmp_path)
        key_path = tmp_path / ".key"
        mode = key_path.stat().st_mode
        assert mode & stat.S_IRUSR
        assert mode & stat.S_IWUSR
        assert not (mode & stat.S_IRGRP)
        assert not (mode & stat.S_IROTH)


class TestEncryptDecrypt:
    def test_encrypt_decrypt_roundtrip(self, tmp_path: Path):
        key = get_or_create_key(tmp_path)
        plaintext = "sk-test-12345"
        token = encrypt(plaintext, key)
        assert token != plaintext
        decrypted = decrypt(token, key)
        assert decrypted == plaintext

    def test_decrypt_plaintext_returns_original(self, tmp_path: Path):
        key = get_or_create_key(tmp_path)
        plaintext = "not-a-token"
        assert decrypt(plaintext, key) == plaintext

    def test_encrypt_empty_returns_empty(self, tmp_path: Path):
        key = get_or_create_key(tmp_path)
        assert encrypt("", key) == ""

    def test_decrypt_empty_returns_empty(self, tmp_path: Path):
        key = get_or_create_key(tmp_path)
        assert decrypt("", key) == ""

    def test_encrypt_with_different_keys(self, tmp_path: Path):
        key_a = get_or_create_key(tmp_path / "a")
        key_b = get_or_create_key(tmp_path / "b")
        plaintext = "secret"
        token_a = encrypt(plaintext, key_a)
        token_b = encrypt(plaintext, key_b)
        assert token_a != token_b
        assert decrypt(token_a, key_a) == plaintext
        assert decrypt(token_b, key_b) == plaintext
        from cryptography.fernet import Fernet, InvalidToken

        with pytest.raises(InvalidToken):
            Fernet(key_b).decrypt(token_a.encode())
