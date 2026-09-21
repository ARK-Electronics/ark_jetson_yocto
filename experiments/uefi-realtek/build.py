#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the failed Realtek UEFI experiment in a new private directory; never flash."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PROFILE = "products/JAJ/fastboot/r39.2.1"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def checked_bytes(data, expected, name):
    if sha256(data) != expected:
        raise ValueError(f"Input checksum mismatch: {name}")
    return data


def collect_inputs(kernel_source, manifest):
    """Read exact Git objects, never the supplied checkout's mutable files."""
    reference = manifest["source_reference"]
    commit = reference["commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Invalid pinned source commit")
    inputs = {}
    for name, digest in reference["files_sha256"].items():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Invalid source path")
        data = subprocess.check_output(
            ["git", "-C", str(kernel_source), "show", f"{commit}:{name}"]
        )
        inputs[name] = checked_bytes(data, digest, name)
    for name, digest in manifest["profile_files_sha256"].items():
        checked_bytes((HERE / name).read_bytes(), digest, name)
    if inputs[f"{PROFILE}/uefi-sources.lock"] != (HERE / "uefi-sources.lock").read_bytes():
        raise ValueError("Published source pins differ from the pinned wrapper profile")
    return inputs


def output_path(repo, name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", name):
        raise ValueError("Output name must contain only letters, digits, '-' and '_'")
    private = repo / "private"
    if private.is_symlink():
        raise ValueError("Refusing a symlinked private output directory")
    output = private / name
    if output.exists() or output.is_symlink():
        raise ValueError("Output already exists; choose a new --output-name")
    return output


def prepare(output, inputs):
    output.parent.mkdir(exist_ok=True)
    output.mkdir()  # Exclusive creation; never reuse another build or its sources.
    source = output / "reference"
    for name, data in inputs.items():
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    (source / PROFILE / "jaj_nvme.defconfig").write_bytes((HERE / "jaj_nvme.defconfig").read_bytes())
    return ["bash", str(source / "scripts/build_fast_boot_uefi.sh"),
            "--bsp", "R39.2.1", "--build-dir", str(output / "build")]


def fv_modules(text):
    modules = []
    for line in text.splitlines():
        if not line.startswith("EFI_FILE_NAME = "):
            continue
        directory = Path(line.split(" = ", 1)[1]).parent.name
        match = re.fullmatch(r"[0-9a-fA-F-]{36}([A-Za-z0-9_]+)", directory)
        if not match:
            raise ValueError("Unrecognized firmware-volume entry")
        if match[1] != "FVMAIN":
            modules.append(match[1])
    if not modules or len(set(modules)) != len(modules):
        raise ValueError("Missing or duplicate firmware-volume modules")
    return sorted(modules)


def verify_output(output, manifest):
    build = output / "build"
    artifacts = build / "artifacts"
    expected = manifest["build"]
    checked_bytes((artifacts / "resolved.config").read_bytes(),
                  manifest["profile_files_sha256"]["resolved.config"], "resolved.config")
    fv = build / "src/Build/jaj_nvme/RELEASE_GCC/FV"
    modules = fv_modules((fv / "FVMAIN.inf").read_text())
    if modules != sorted(expected["fv"]["all_modules"]):
        raise ValueError("Firmware-volume module inventory changed")
    sections = list((fv / "Ffs").glob("*RtkUndiDxe/*pe32"))
    if len(sections) != 1:
        raise ValueError("Expected exactly one Realtek PE32 section")
    section = sections[0].read_bytes()
    if len(section) < 4 or int.from_bytes(section[:3], "little") != len(section) or section[3] != 0x10:
        raise ValueError("Unexpected Realtek PE32 section header")
    checked_bytes(section[4:], expected["realtek"]["vendor_binary_sha256"], "Realtek PE32 payload")
    firmware = (artifacts / expected["firmware"]["filename"]).read_bytes()
    if not 0 < len(firmware) <= expected["firmware"]["partition_capacity_bytes"]:
        raise ValueError("Firmware does not fit the measured UEFI partition")
    result = {"schema_version": 1, "status": "built_verified_not_deployed",
              "firmware_bytes": len(firmware), "firmware_sha256": sha256(firmware),
              "matches_measured_firmware": sha256(firmware) == expected["firmware"]["sha256"],
              "resolved_config_matches": True, "fv_modules": modules,
              "realtek_pe32_matches": True}
    (output / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel-source", type=Path, required=True,
                        help="Existing ark_jetson_kernel checkout containing the pinned commit")
    parser.add_argument("--output-name", default="uefi-realtek-reproduction")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="Read/check inputs only; no output or Docker")
    action.add_argument("--prepare-only", action="store_true", help="Extract inputs and command only; no build")
    args = parser.parse_args()
    manifest = json.loads((HERE / "provenance.json").read_text())
    try:
        output = output_path(REPO, args.output_name)
        inputs = collect_inputs(args.kernel_source.resolve(), manifest)
        if args.check:
            print("Pinned source objects, profile and output location verified; no changes made.")
            return
        command = prepare(output, inputs)
        (output / "command.json").write_text(json.dumps(command, indent=2) + "\n")
        (output / "experiment-provenance.json").write_bytes((HERE / "provenance.json").read_bytes())
        if args.prepare_only:
            print(f"Prepared {output}; command is recorded in command.json. No build performed.")
            return
        subprocess.run(command, check=True)
        result = verify_output(output, manifest)
        print(f"Built and verified {result['firmware_bytes']} bytes; SHA256 {result['firmware_sha256']}")
        print("No staging, deployment or device access performed.")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"uefi-realtek: {error}\n")


if __name__ == "__main__":
    main()
