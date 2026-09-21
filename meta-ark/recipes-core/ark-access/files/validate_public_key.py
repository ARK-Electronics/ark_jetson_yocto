# SPDX-License-Identifier: MIT
"""Validate one OpenSSH public key before installing authorized_keys.

Only standard-library modules are used. Error messages never include key data.
"""
import base64
import binascii
import struct


# NIST prime-field short Weierstrass curves: y^2 = x^3 - 3*x + b (mod p).
CURVES = {
    "nistp256": (32, (1 << 256) - (1 << 224) + (1 << 192) + (1 << 96) - 1,
                 int("5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b", 16)),
    "nistp384": (48, (1 << 384) - (1 << 128) - (1 << 96) + (1 << 32) - 1,
                 int("b3312fa7e23ee7e4988e056be3f82d19181d9c6efe8141120314088f5013875ac656398d8a2ed19d2a85c8edd3ec2aef", 16)),
    "nistp521": (66, (1 << 521) - 1,
                 int("0051953eb9618e1c9a1f929a21a0b68540eea2da725b99b315f3b8b489918ef109e156193951ec7e937b1652c0bd3bb1bf073573df883d2c34f1ef451fd46b503f00", 16)),
}


class SSHFields:
    def __init__(self, blob):
        self.blob = blob
        self.offset = 0

    def string(self):
        if len(self.blob) - self.offset < 4:
            raise ValueError("truncated SSH field length")
        length, = struct.unpack_from(">I", self.blob, self.offset)
        self.offset += 4
        end = self.offset + length
        if end > len(self.blob):
            raise ValueError("truncated SSH field")
        result = self.blob[self.offset:end]
        self.offset = end
        return result

    def positive_mpint(self):
        field = self.string()
        if not field or field[0] & 0x80:
            raise ValueError("RSA fields must be positive SSH mpints")
        if field[0] == 0 and (len(field) == 1 or not field[1] & 0x80):
            raise ValueError("noncanonical RSA mpint")
        return int.from_bytes(field, "big")

    def finish(self):
        if self.offset != len(self.blob):
            raise ValueError("unexpected trailing SSH fields")


def validate_ec_point(curve, point):
    width, prime, coefficient = CURVES[curve]
    if len(point) == 1 + 2 * width and point[0] == 4:
        x = int.from_bytes(point[1:1 + width], "big")
        y = int.from_bytes(point[1 + width:], "big")
    elif len(point) == 1 + width and point[0] in (2, 3):
        x = int.from_bytes(point[1:], "big")
        rhs = (x * x * x - 3 * x + coefficient) % prime
        # All supported NIST primes are 3 modulo 4.
        y = pow(rhs, (prime + 1) // 4, prime)
        if y % 2 != point[0] % 2:
            y = prime - y
    else:
        raise ValueError("invalid ECDSA point encoding or length")
    if x >= prime or y >= prime or (y * y - x * x * x + 3 * x - coefficient) % prime:
        raise ValueError("ECDSA point is not on the named curve")


def validate_public_key(value):
    """Return a normalized key line, or raise ValueError for malformed input."""
    if not isinstance(value, str):
        raise ValueError("public key must be text")
    line = value.strip()
    if not line or len(line) > 32768:
        raise ValueError("public key is empty or exceeds 32 KiB")
    if any((ord(char) < 32 and char != "\t") or ord(char) == 127 for char in line):
        raise ValueError("public key must contain one line without control characters")
    parts = line.split(None, 2)
    if len(parts) < 2:
        raise ValueError("expected an OpenSSH key type and base64 blob")
    algorithm, encoded = parts[:2]
    accepted = {"ssh-ed25519", "ssh-rsa"} | {"ecdsa-sha2-" + curve for curve in CURVES}
    if algorithm not in accepted:
        raise ValueError("supported key types are Ed25519, RSA and NIST ECDSA")
    try:
        blob = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("invalid public-key base64") from None
    if base64.b64encode(blob).decode("ascii") != encoded:
        raise ValueError("noncanonical public-key base64")
    fields = SSHFields(blob)
    if fields.string() != algorithm.encode("ascii"):
        raise ValueError("public-key header does not match the SSH blob type")
    if algorithm == "ssh-ed25519":
        if len(fields.string()) != 32:
            raise ValueError("Ed25519 public key must contain exactly 32 bytes")
    elif algorithm == "ssh-rsa":
        exponent = fields.positive_mpint()
        modulus = fields.positive_mpint()
        if exponent < 3 or exponent % 2 != 1 or modulus <= exponent or modulus % 2 != 1:
            raise ValueError("invalid RSA exponent or modulus")
        if modulus.bit_length() < 1024:
            raise ValueError("RSA modulus is smaller than OpenSSH's 1024-bit minimum")
    else:
        curve = algorithm.removeprefix("ecdsa-sha2-")
        if fields.string() != curve.encode("ascii"):
            raise ValueError("ECDSA curve name does not match the key type")
        validate_ec_point(curve, fields.string())
    fields.finish()
    return " ".join(parts)
