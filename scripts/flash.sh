#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
umask 077
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

usage() {
    cat <<'USAGE'
Usage: flash.sh (--artifact FILE | --bundle DIR) [options]

  --check                    Validate and stage the bundle; no Docker or device access
  --sha256 HASH              Verify the supplied archive's SHA-256
  --work-dir DIR             New private directory for this run (must not exist)
  --usb-instance PORT        Select an exact recovery USB path, including hub ports
  --confirm-erase-nvme       Acknowledge replacement of the ENTIRE target NVMe
  --full-flash              Also replace QSPI boot firmware (default: external-only)
  --confirm-write-qspi       Required with --full-flash
  --privileged-container    Explicit fallback for hosts rejecting scoped device access
  -h, --help                Show this help

Only ark-headless-image / ark-jaj-orin-nx / R39.2.1 / P3767-0000 is supported.
Default flashing preserves QSPI; it does not preserve any NVMe partition.
Run as your normal Docker-enabled user. Actual flashing requires a backup.
See docs/flashing.md before use. Bundles contain privileged executable code.
USAGE
}
die() { echo "ERROR: $*" >&2; exit 1; }
need_value() { (($# >= 2)) && [[ -n $2 ]] || die "Missing value for $1"; }
artifact= bundle= work_dir= expected_sha= usb_instance=
check_only=0 full_flash=0 confirm_nvme=0 confirm_qspi=0 privileged=0
while (($#)); do
    case "$1" in
        --artifact) need_value "$@"; artifact=$2; shift 2 ;;
        --bundle) need_value "$@"; bundle=$2; shift 2 ;;
        --work-dir) need_value "$@"; work_dir=$2; shift 2 ;;
        --sha256) need_value "$@"; expected_sha=$2; shift 2 ;;
        --usb-instance) need_value "$@"; usb_instance=$2; shift 2 ;;
        --check) check_only=1; shift ;;
        --confirm-erase-nvme) confirm_nvme=1; shift ;;
        --full-flash) full_flash=1; shift ;;
        --confirm-write-qspi) confirm_qspi=1; shift ;;
        --privileged-container) privileged=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done
[[ -n $artifact && -z $bundle || -z $artifact && -n $bundle ]] || die "Supply exactly one of --artifact and --bundle"
[[ -z $expected_sha || -n $artifact && $expected_sha =~ ^[[:xdigit:]]{64}$ ]] || die "--sha256 requires an archive and a 64-digit hash"
[[ -z $usb_instance || $usb_instance =~ ^[0-9]+-[0-9]+(\.[0-9]+)*$ ]] || die "Invalid USB instance"
((full_flash || !confirm_qspi)) || die "--confirm-write-qspi requires --full-flash"
if ((!check_only)); then
    ((confirm_nvme)) || die "Flashing erases every NVMe partition; supply --confirm-erase-nvme"
    ((!full_flash || confirm_qspi)) || die "Full flashing replaces QSPI; supply --confirm-write-qspi"
    [[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || die "Flashing requires a native x86_64 Linux host"
fi
for command in python3 debugfs; do
    command -v "$command" >/dev/null || die "Missing host command: $command"
done
python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' || die "Python 3.12 or later is required for safe archive extraction"
if [[ -n $artifact ]]; then
    artifact=$(readlink -f -- "$artifact")
    [[ -f $artifact ]] || die "Archive not found"
    [[ $artifact != *.zst ]] || command -v zstd >/dev/null || die "Install zstd to read this archive"
else
    bundle=$(readlink -f -- "$bundle")
    [[ -d $bundle ]] || die "Bundle directory not found"
fi
if [[ -n $work_dir ]]; then
    work_dir=$(realpath -m -- "$work_dir")
    mkdir -m 0700 -- "$work_dir" || die "--work-dir must name a new directory"
else
    mkdir -p -- "$repo/private/flash"
    work_dir=$(mktemp -d "$repo/private/flash/run-XXXXXXXX")
fi
[[ $work_dir != *','* && $work_dir != *$'\n'* ]] || die "Work directory cannot contain comma or newline (Docker mount syntax)"
mkdir -- "$work_dir/bundle"
echo "Private work directory: $work_dir"
if [[ -n $bundle ]]; then
    cp -a --reflink=auto --sparse=always -- "$bundle/." "$work_dir/bundle/"
fi

# Parse metadata as data; do not source artifact-controlled shell code on the host.
python3 - "$artifact" "$work_dir" "$expected_sha" <<'PY_VALIDATE'
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET

archive, work, expected = sys.argv[1:]
root = Path(work) / "bundle"
def fail(message):
    raise SystemExit("ERROR: " + message)
archive_sha = None
if archive:
    with open(archive, "rb") as stream:
        archive_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    if expected and archive_sha != expected.lower():
        fail("Archive SHA-256 does not match")
    if archive.endswith(".zst"):
        with subprocess.Popen(["zstd", "-dc", "--", archive], stdout=subprocess.PIPE) as proc:
            with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
                tar.extractall(root, filter="data")
            if proc.wait():
                fail("zstd decompression failed")
    else:
        with tarfile.open(archive, "r:*") as tar:
            tar.extractall(root, filter="data")

# Also reject external symlinks and device files in an already extracted bundle.
for current, dirs, files in os.walk(root, followlinks=False):
    for name in dirs + files:
        path = Path(current) / name
        if not path.resolve().is_relative_to(root.resolve()):
            fail("Bundle link escapes its directory: " + str(path.relative_to(root)))
        kind = path.lstat().st_mode
        if not (stat.S_ISREG(kind) or stat.S_ISDIR(kind) or stat.S_ISLNK(kind)):
            fail("Bundle contains a special file: " + str(path.relative_to(root)))

def required(name):
    path = root / name
    if not path.is_file() or path.stat().st_size == 0:
        fail("Missing or empty bundle file: " + name)
    return path

def variables(name):
    result = {}
    for line in required(name).read_text().splitlines():
        match = re.fullmatch(r"([A-Za-z_][A-Za-z_0-9]*(?:\[[A-Z0-9_]+\])?)=(.*)", line.strip())
        if match:
            words = shlex.split(match[2], comments=True)
            if len(words) > 1 or match[1] in result:
                fail("Ambiguous assignment in " + name)
            result[match[1]] = words[0] if words else ""
        elif line.strip() and not line.lstrip().startswith("#"):
            fail("Unexpected non-assignment in " + name)
    return result

def require_values(values, expected_values, source):
    for key, value in expected_values.items():
        if values.get(key) != value:
            fail(f"{source}: expected {key}={value!r}, got {values.get(key)!r}")

env = variables(".env.initrd-flash")
require_values(env, {
    "MACHINE": "ark-jaj-orin-nx", "CHIPID": "0x23",
    "ROOTFS_IMAGE": "ark-headless-image.ext4", "ROOTFS_DEVICE": "nvme0n1",
    "BOOTDEV": "nvme0n1p1", "EXTERNAL_ROOTFS_DRIVE": "1", "NO_INTERNAL_STORAGE": "1",
    "FLASH_HELPER": "tegra-flash-helper.sh", "LNXFILE": "boot.img",
    "DEFAULTS[BOARDID]": "3767", "DEFAULTS[BOARDSKU]": "0000",
}, ".env.initrd-flash")
flashvars = variables("flashvars")
require_values(flashvars, {
    "CHIPID": "0x23", "CHECK_BOARDID": "3767", "CHECK_BOARDSKU": "0000",
    "DTB_FILE": "tegra234-ark-jaj-p3767-0000-super.dtb",
    "BPFDTB_FILE": "tegra234-bpmp-3767-0000-3768-super.dtb",
    "PINMUX_CONFIG": "tegra234-mb1-bct-pinmux-ark-jaj.dtsi",
    "PMC_CONFIG": "tegra234-mb1-bct-padvoltage-ark-jaj.dtsi",
    "MB2BCT_CFG": "tegra234-mb2-bct-misc-ark-jaj.dts",
}, "flashvars")
require_values(variables("bsp_version"), {"BSP_BRANCH": "39", "BSP_MAJOR": "2", "BSP_MINOR": "1"}, "bsp_version")
if (root / ".presigning-vars").exists():
    fail("Presigned/secure-boot bundles require a separate reviewed signing flow")

# OE4T 2e37d1673d25fb92440bcf6db8dcf1076e822037, with ARK's hub-safe
# initrd-flash patch. Reject older helpers that can disconnect an ancestor hub.
helper_hashes = {
    "initrd-flash": "d3fb201ccfc7159be09555ff48a5b2b8808c6b561ec83fdb5d4556198c4587ff",
    "tegra-flash-helper.sh": "e769087d14dae1c0479de5ce8bcfe96b34fd763178e984eedf0ebbd9516f3939",
    "make-sdcard": "88a256622c676751b2e9de8d92f390c127c10a8e2c41ed26b9da9d9919d1d762",
    "find-jetson-usb": "2393e0acb1704fa9198e8976f91cc65bff845f84eb048567fbd20adc79cd6fe3",
    "nvflashxmlparse": "d9640a9250f6c66f2991cf8a532444133de7a5fa819a59eac6ef05baa110350c",
    "nvbct-config": "abd5d002977922f2e865dbd518f8399a21aaf62aaca865e61a3701db475eb9cc",
}
for name, expected_hash in helper_hashes.items():
    path = required(name)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
        fail("Unexpected helper revision: " + name + "; rebuild with this repository's pinned layers and patches")
    if not os.access(path, os.X_OK):
        fail("Helper is not executable: " + name)
for name in ("initrd-flash.img", "boot.img", "tegrarcm_v2", "tegraflash.py", "chkbdinfo", "flash.xml.in"):
    required(name)
for key in ("DTB_FILE", "BPFDTB_FILE", "PINMUX_CONFIG", "PMC_CONFIG", "MB2BCT_CFG"):
    required(flashvars[key])
layout = ET.parse(required("external-flash.xml.in")).getroot()
devices = layout.findall("device")
if len(devices) != 1 or devices[0].get("type") != "external":
    fail("Expected one external storage device in flash layout")
parts = {p.get("name") for p in devices[0].findall("partition")}
if "APP" not in parts or "APP_b" in parts:
    fail("Expected the supported single-root APP layout")
image = required(env["ROOTFS_IMAGE"])
with image.open("rb") as stream:
    stream.seek(1080)
    if stream.read(2) != b"\x53\xef":
        fail("Rootfs is not a raw ext4 image")
release = subprocess.run(["debugfs", "-R", "cat /usr/lib/os-release", str(image)], text=True,
                         capture_output=True, check=True, timeout=30).stdout
os_id = next((shlex.split(line[3:])[0] for line in release.splitlines() if line.startswith("ID=")), None)
if os_id != "ark-headless":
    fail("Rootfs /usr/lib/os-release is not ark-headless")
report = {"machine": env["MACHINE"], "image": env["ROOTFS_IMAGE"], "os_id": os_id,
          "bsp": "39.2.1", "module": "P3767-0000", "target_disk": env["ROOTFS_DEVICE"],
          "archive_sha256": archive_sha, "helper_sha256": helper_hashes}
(Path(work) / "bundle-validation.json").write_text(json.dumps(report, indent=2) + "\n")
print(f"Validated {report['machine']} / {report['image']} / R{report['bsp']} / {report['module']}")
if archive_sha:
    print("Archive SHA-256: " + archive_sha)
PY_VALIDATE

if ((full_flash)); then
    echo "Selected operation: replace all NVMe partitions AND QSPI firmware."
else
    echo "Selected operation: replace all NVMe partitions; preserve QSPI firmware."
fi
((!check_only)) || exit 0
for command in docker; do
    command -v "$command" >/dev/null || die "Missing host command: $command"
done
[[ -d /dev/bus/usb && -d /run/udev && -e /sys/bus/usb/drivers/usb/unbind ]] || die "Host must expose USB, udev, and USB bind/unbind controls"
[[ -z ${DOCKER_HOST:-} || $DOCKER_HOST == unix://* ]] || die "Use a local rootful Docker daemon"
endpoint=$(docker context inspect --format '{{(index .Endpoints "docker").Host}}')
[[ $endpoint == unix://* ]] || die "A remote Docker context cannot flash this host's USB device"
if docker info --format '{{json .SecurityOptions}}' | grep -q 'name=rootless'; then
    die "Rootless Docker cannot manage the temporary host udev rule or flash devices"
fi
image="ark-jetson-yocto-flasher:$(sha256sum "$repo/docker/Dockerfile.flash" | cut -c1-16)"
if ! docker image inspect "$image" >/dev/null 2>&1; then
    docker build --file "$repo/docker/Dockerfile.flash" --tag "$image" "$repo/docker"
fi
usb_instance=$(python3 - "$usb_instance" <<'PY_USB'
from pathlib import Path
import sys
requested = sys.argv[1]
matches = []
for path in Path("/sys/bus/usb/devices").iterdir():
    try:
        if (path / "idVendor").read_text().strip() == "0955" and (path / "idProduct").read_text().strip() == "7323":
            matches.append(path.name)
    except (FileNotFoundError, NotADirectoryError):
        pass
if requested:
    if requested not in matches:
        raise SystemExit("ERROR: selected port does not contain an Orin NX 16GB in Force Recovery (0955:7323)")
    print(requested)
elif len(matches) == 1:
    print(matches[0])
else:
    raise SystemExit("ERROR: expected exactly one Orin NX 16GB in Force Recovery; specify --usb-instance when several are connected")
PY_USB
)
echo "Selected recovery USB path: $usb_instance"

# Only this short helper can write /run/udev. Its rule matches the exact USB
# port and OE4T gadget; no existing host rules or services are changed.
run_id=$(python3 -c 'import uuid; print(uuid.uuid4().hex)')
rule_name="99-ark-yocto-flash-$run_id.rules"
rules_dir_created=0
[[ -d /run/udev/rules.d ]] || rules_dir_created=1
manage_rule() {
    docker run --rm --interactive --user 0:0 --network none --entrypoint /bin/bash \
        --mount type=bind,src=/run/udev,dst=/run/udev \
        "$image" -s -- "$1" "$rule_name" "$usb_instance" "$rules_dir_created" <<'RULE_HELPER'
set -euo pipefail
[[ $2 =~ ^99-ark-yocto-flash-[0-9a-f]{32}\.rules$ && $3 =~ ^[0-9]+-[0-9]+(\.[0-9]+)*$ ]] || exit 1
rule_file="/run/udev/rules.d/$2"
rule=$(printf 'ACTION=="add|change", SUBSYSTEM=="block", SUBSYSTEMS=="usb", KERNELS=="%s", ATTRS{idVendor}=="1d6b", ATTRS{idProduct}=="0104", ENV{UDISKS_IGNORE}="1", ENV{UDISKS_AUTO}="0"' "$3")
case "$1" in
    create)
        mkdir -p /run/udev/rules.d
        # Refuse to overwrite an existing path, including a dangling symlink.
        [[ ! -e $rule_file && ! -L $rule_file ]] || exit 1
        (umask 022; set -o noclobber; printf '%s\n' "$rule" > "$rule_file")
        if ! udevadm control --reload-rules; then
            rm -f -- "$rule_file"
            if [[ $4 == 1 ]]; then rmdir /run/udev/rules.d 2>/dev/null || true; fi
            exit 1
        fi
        ;;
    remove)
        if [[ -e $rule_file || -L $rule_file ]]; then
            [[ -f $rule_file && ! -L $rule_file && $(cat "$rule_file") == "$rule" ]] || {
                echo "Refusing to remove a changed udev rule: $rule_file" >&2; exit 1;
            }
            rm -- "$rule_file"
        fi
        if [[ $4 == 1 ]]; then rmdir /run/udev/rules.d 2>/dev/null || true; fi
        udevadm control --reload-rules
        ;;
    *) exit 1 ;;
esac
RULE_HELPER
}
rule_installed=0
container_name=
cleanup() {
    local result=$?
    trap - EXIT
    if [[ -n $container_name ]]; then
        docker rm -f "$container_name" >/dev/null 2>&1 || true
    fi
    if ((rule_installed)); then
        manage_rule remove || {
            echo "ERROR: remove the owned temporary rule /run/udev/rules.d/$rule_name and reload udev" >&2
            result=1
        }
    fi
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf '/run/udev/rules.d/%s\n' "$rule_name" > "$work_dir/host-udev-rule.txt"
echo "Temporary automount rule: /run/udev/rules.d/$rule_name"
rule_installed=1
manage_rule create

container_name="ark-yocto-flash-$run_id"
docker_args=(run --rm --init --interactive --name "$container_name" --user 0:0
    --network none --env USER=root --env TEGRAFLASH_CHECK_USB_INSTANCE=yes
    --mount "type=bind,src=$work_dir/bundle,dst=/work"
    --mount type=bind,src=/dev,dst=/dev,bind-propagation=rslave
    --mount type=bind,src=/run/udev,dst=/run/udev,readonly
    --mount type=bind,src=/sys/bus/usb/drivers/usb,dst=/sys/bus/usb/drivers/usb
    --workdir /work)
if ((privileged)); then
    docker_args+=(--privileged)
else
    docker_args+=(--cap-add SYS_ADMIN --security-opt apparmor=unconfined --security-opt seccomp=unconfined
        --device-cgroup-rule 'c 189:* rw' --device-cgroup-rule 'b 8:* rw' --device-cgroup-rule 'b 65:* rw')
fi
flash_args=(--external-only)
((!full_flash)) || flash_args=()
# No identity variables are forwarded from the host. Clear them inside Docker
# too, so the upstream EEPROM probe/checks cannot be bypassed by image defaults.
if ! docker "${docker_args[@]}" "$image" -s -- "$usb_instance" "${flash_args[@]}" <<'CONTAINER' 2>&1 | tee "$work_dir/console.log"
set -euo pipefail
usb_instance=$1
shift
unset BOARDID FAB BOARDSKU BOARDREV CHIPREV CHIP_SKU RAMCODE serial_number BR_CID
rm -f boardvars.sh .found-jetson
./tegra-flash-helper.sh --usb-instance "$usb_instance" --get-board-info
python3 - <<'PY_BOARD'
from pathlib import Path
import shlex
values = {}
for line in Path("boardvars.sh").read_text().splitlines():
    if "=" in line:
        key, value = line.split("=", 1)
        parsed = shlex.split(value)
        values[key] = parsed[0] if parsed else ""
if values.get("BOARDID") != "3767" or values.get("BOARDSKU") != "0000":
    raise SystemExit("ERROR: actual EEPROM is not P3767-0000")
if not values.get("FAB") or values["FAB"] in {"TS1", "EB1"}:
    raise SystemExit("ERROR: module FAB does not support this Super configuration")
if not values.get("serial_number"):
    raise SystemExit("ERROR: missing module serial; refusing ambiguous mass-storage matching")
print("Actual EEPROM: P3767-0000; supported Super FAB; serial available for gadget matching")
PY_BOARD
exec ./initrd-flash --usb-instance "$usb_instance" "$@"
CONTAINER
then
    die "Flashing failed; keep private logs in $work_dir and recover using docs/flashing.md"
fi
# Pinned upstream prints target status but can still return zero for FAILED.
awk '/^Final status:/ {status=$0} END {exit status != "Final status: SUCCESS"}' "$work_dir/console.log" || die "Target did not report SUCCESS; inspect $work_dir"
echo "Target reported SUCCESS. Logs: $work_dir (boot validation is still required)."
