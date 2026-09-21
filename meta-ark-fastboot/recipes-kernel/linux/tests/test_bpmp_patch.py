#!/usr/bin/env python3
"""Validate the recipe's actual source guards and patch using local kernel sources."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import types
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
KERNEL = Path(os.environ.get("ARK_BPMP_KERNEL_SOURCE", str(
    ROOT / "build/tmp/work-shared/ark-jaj-orin-nx/kernel-source")))
APPEND = HERE.parent / "linux-noble-nvidia-tegra_%.bbappend"
PATCH = HERE.parent / "files/0001-tegra-bpmp-optional-async-debugfs.patch"
FILES = ("drivers/firmware/tegra/bpmp.c", "drivers/firmware/tegra/bpmp-debugfs.c",
         "include/soc/tegra/bpmp.h")


class GuardFailure(Exception):
    pass


def fatal(message):
    raise GuardFailure(message)


class Data:
    def __init__(self, source, enabled="1"):
        self.values = {"S": str(source), "ARK_BPMP_DEBUGFS_ASYNC": enabled}

    def getVar(self, name):
        return self.values.get(name)


class BpmpPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        content = APPEND.read_text()
        code = content[content.index("def ark_bpmp_verify_sources("):
                       content.index("python ark_bpmp_check_original()")]
        namespace = {"bb": types.SimpleNamespace(fatal=fatal)}
        exec(compile(code, str(APPEND), "exec"), namespace)
        cls.guard = staticmethod(namespace["ark_bpmp_verify_sources"])
        for relative in FILES:
            if not (KERNEL / relative).is_file():
                raise RuntimeError("Set ARK_BPMP_KERNEL_SOURCE to an unpacked pinned R39 kernel tree")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ark-bpmp-test-")
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)
        for relative in FILES:
            destination = self.source / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(KERNEL / relative, destination)
        self.data = Data(self.source)

    def apply_patch(self):
        subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "-i", str(PATCH)],
                       cwd=self.source, check=True, capture_output=True, text=True)

    def test_baseline_does_not_access_source(self):
        disabled = Data(self.source / "absent", enabled="0")
        self.guard(disabled)
        self.guard(disabled, patched=True)

    def test_audited_original_sources(self):
        self.guard(self.data)

    def test_strict_patch_and_complete_output_hash(self):
        self.guard(self.data)
        self.apply_patch()
        self.guard(self.data, patched=True)

    def test_original_is_not_accepted_as_patched(self):
        with self.assertRaisesRegex(GuardFailure, "patched source checksum mismatch"):
            self.guard(self.data, patched=True)

    def test_patched_is_not_accepted_as_original(self):
        self.apply_patch()
        with self.assertRaisesRegex(GuardFailure, "original source checksum mismatch"):
            self.guard(self.data)

    def test_changed_source_or_companions_fail_closed(self):
        for relative in FILES:
            with self.subTest(relative=relative):
                path = self.source / relative
                original = path.read_bytes()
                path.write_bytes(original + b"\n/* changed source */\n")
                with self.assertRaisesRegex(GuardFailure, "source checksum mismatch"):
                    self.guard(self.data)
                path.write_bytes(original)

    def test_changed_patched_output_fails_closed(self):
        self.apply_patch()
        path = self.source / FILES[0]
        path.write_bytes(path.read_bytes() + b"\n/* unexpected patch */\n")
        with self.assertRaisesRegex(GuardFailure, "patched source checksum mismatch"):
            self.guard(self.data, patched=True)

    def test_missing_companion_fails_closed(self):
        (self.source / FILES[1]).unlink()
        with self.assertRaisesRegex(GuardFailure, "source verification failed"):
            self.guard(self.data)


if __name__ == "__main__":
    unittest.main()
