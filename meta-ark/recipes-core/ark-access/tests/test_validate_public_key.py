# SPDX-License-Identifier: MIT
"""Run with python3 -m unittest discover -s <this directory>."""
import base64
import importlib.util
import json
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validator", ROOT / "files/validate_public_key.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)
KEYS = json.loads((ROOT / "tests/public-keys.json").read_text())


def field(data):
    return struct.pack(">I", len(data)) + data


def line(algorithm, *fields, suffix=b""):
    return algorithm + " " + base64.b64encode(b"".join(field(f) for f in fields) + suffix).decode()


def mpint(value):
    data = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return b"\0" + data if data[0] & 128 else data


class PublicKeyValidation(unittest.TestCase):
    def test_real_keygen_public_keys(self):
        for name, key in KEYS.items():
            with self.subTest(algorithm=name):
                self.assertEqual(validator.validate_public_key(key), key)

    def test_rejects_readme_placeholder_and_bad_base64(self):
        for value in ("", "ssh-ed25519 AAAA... your-key", "ssh-rsa !!!", "ssh-ed25519 A", "ssh-ed25519 é"):
            with self.subTest(case=value[:12]):
                with self.assertRaises(ValueError):
                    validator.validate_public_key(value)

    def test_rejects_multiline_and_controls(self):
        for suffix in ("\n" + KEYS["rsa2048"], "\rcomment", "\0", "\x7f"):
            with self.assertRaises(ValueError):
                validator.validate_public_key(KEYS["ed25519"] + suffix)

    def test_all_truncations_rejected(self):
        for name, key in KEYS.items():
            algorithm, encoded, *_ = key.split()
            blob = base64.b64decode(encoded)
            for length in range(len(blob)):
                with self.subTest(algorithm=name, length=length):
                    with self.assertRaises(ValueError):
                        validator.validate_public_key(algorithm + " " + base64.b64encode(blob[:length]).decode())

    def test_header_blob_mismatch(self):
        for other in ("ssh-rsa", "ecdsa-sha2-nistp256"):
            with self.assertRaises(ValueError):
                validator.validate_public_key(KEYS["ed25519"].replace("ssh-ed25519", other, 1))

    def test_trailing_data_rejected(self):
        for suffix in (b"\0", field(b"extra")):
            with self.assertRaises(ValueError):
                validator.validate_public_key(line("ssh-ed25519", b"ssh-ed25519", b"x" * 32, suffix=suffix))

    def test_ed25519_length(self):
        for length in (0, 1, 31, 33, 64):
            with self.assertRaises(ValueError):
                validator.validate_public_key(line("ssh-ed25519", b"ssh-ed25519", b"x" * length))

    def test_rsa_invalid_fields(self):
        modulus = mpint((1 << 2047) + 1)
        for exponent in (b"", b"\0", b"\x80", b"\0\x03", b"\x01", b"\x02", b"\x04"):
            with self.assertRaises(ValueError):
                validator.validate_public_key(line("ssh-rsa", b"ssh-rsa", exponent, modulus))
        for bad_modulus in (b"", b"\0", b"\x80", b"\x03", mpint(1 << 2047)):
            with self.assertRaises(ValueError):
                validator.validate_public_key(line("ssh-rsa", b"ssh-rsa", b"\x03", bad_modulus))

    def test_ecdsa_curve_mismatch_and_invalid_points(self):
        for curve, point in ((b"nistp384", b"\x04" + b"x" * 64), (b"nistp256", b"\x04" + b"x" * 64), (b"nistp256", b"\0"), (b"nistp256", b"\x04" + b"x" * 63)):
            with self.assertRaises(ValueError):
                validator.validate_public_key(line("ecdsa-sha2-nistp256", b"ecdsa-sha2-nistp256", curve, point))

    def test_ecdsa_compressed_points(self):
        for curve in validator.CURVES:
            key = KEYS["ecdsa" + curve.removeprefix("nistp")]
            algorithm, encoded, *_ = key.split()
            reader = validator.SSHFields(base64.b64decode(encoded))
            kind, name, point = reader.string(), reader.string(), reader.string()
            width = validator.CURVES[curve][0]
            compressed = bytes([2 | (point[-1] & 1)]) + point[1:1 + width]
            self.assertEqual(validator.validate_public_key(line(algorithm, kind, name, compressed)), line(algorithm, kind, name, compressed))

    def test_normalizes_whitespace_without_losing_comment(self):
        key = KEYS["ed25519"]
        self.assertEqual(validator.validate_public_key(" \t" + key.replace(" ", "\t", 1) + "\n"), key)


if __name__ == "__main__":
    unittest.main()
