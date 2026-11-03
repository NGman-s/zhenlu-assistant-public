from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

MODULE_PATH = Path(__file__).resolve().parents[1] / "device_identity.py"
spec = importlib.util.spec_from_file_location("device_identity", MODULE_PATH)
identity = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(identity)


def key_pair():
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return private, public


def test_only_matching_key_and_challenge_are_accepted():
    private, public = key_pair()
    _, wrong_public = key_pair()
    nonce = bytes(range(32))
    signature = private.sign(identity.DOMAIN + nonce, ec.ECDSA(hashes.SHA256()))
    assert identity.verify_response(public, nonce, signature)
    assert not identity.verify_response(wrong_public, nonce, signature)
    assert not identity.verify_response(public, bytes(reversed(nonce)), signature)
    assert not identity.verify_response(public, nonce, b"invalid")
    assert not identity.verify_response(public, b"short", signature)


def test_each_verification_uses_fresh_challenge(monkeypatch):
    private, public = key_pair()
    challenges = []
    monkeypatch.setattr(identity, "locate_port", lambda selected: "COM4")
    def exchange(port, command, prefix):
        nonce = bytes.fromhex(command.removeprefix(b"ZL1 SIGN ").decode())
        challenges.append(nonce)
        return private.sign(identity.DOMAIN + nonce, ec.ECDSA(hashes.SHA256()))
    monkeypatch.setattr(identity, "exchange", exchange)
    assert identity.verify_device(public)
    assert identity.verify_device(public)
    assert challenges[0] != challenges[1]


def test_bad_public_keys_are_rejected():
    with pytest.raises(identity.DeviceError):
        identity.load_public(b"not a key")
    wrong = ec.generate_private_key(ec.SECP384R1()).public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    with pytest.raises(identity.DeviceError):
        identity.load_public(wrong)


def test_exchange_handles_fragmented_serial_data(monkeypatch):
    class FakePort:
        dtr = False
        rts = False
        port = None
        def __init__(self, **kwargs):
            self.chunks = iter([b"boot log\nZL1 ", b"SIG 01", b"02\r", b"\n"])
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def reset_input_buffer(self):
            pass
        def write(self, data):
            assert data == b"ZL1 SIGN abc\n"
        def flush(self):
            pass
        def read(self, size):
            return next(self.chunks, b"")
    monkeypatch.setattr(identity.serial, "Serial", FakePort)
    assert identity.exchange("COM4", b"ZL1 SIGN abc", b"ZL1 SIG ") == b"\x01\x02"
