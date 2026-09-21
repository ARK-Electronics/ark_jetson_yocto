#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Focused checks for isolated input preparation and artifact validation."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("uefi_realtek_build", Path(__file__).with_name("build.py"))
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class BuildTests(unittest.TestCase):
    def test_checksum_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "checksum"):
            build.checked_bytes(b"altered", build.sha256(b"expected"), "input")

    def test_output_traversal_and_existing_output_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            for name in ["../outside", "/absolute", "a/b", "", "$(id)"]:
                with self.assertRaises(ValueError):
                    build.output_path(repo, name)
            (repo / "private/existing").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "already exists"):
                build.output_path(repo, "existing")

    def test_symlinked_output_root_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "private").symlink_to(repo, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                build.output_path(repo, "new")

    def test_preparation_is_separate_and_never_starts_build(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new"
            original = b"original profile\n"
            inputs = {f"{build.PROFILE}/jaj_nvme.defconfig": original,
                      "scripts/build_fast_boot_uefi.sh": b"#!/bin/bash\n"}
            with patch.object(build.subprocess, "run") as run:
                command = build.prepare(output, inputs)
                run.assert_not_called()
            self.assertEqual(inputs[f"{build.PROFILE}/jaj_nvme.defconfig"], original)
            self.assertEqual((output / "reference" / build.PROFILE / "jaj_nvme.defconfig").read_bytes(),
                             (build.HERE / "jaj_nvme.defconfig").read_bytes())
            self.assertEqual(command[-3:], ["R39.2.1", "--build-dir", str(output / "build")])
            with self.assertRaises(FileExistsError):
                build.prepare(output, inputs)

    def test_fv_inventory_excludes_container_only(self):
        guid = "22DE1691-D65D-456A-993E-A253DD1F308C"
        records = "\n".join(f"EFI_FILE_NAME = /build/Ffs/{guid}{name}/{guid}.ffs"
                            for name in ["FVMAIN", "RtkUndiDxe", "SnpDxe"])
        self.assertEqual(build.fv_modules(records), ["RtkUndiDxe", "SnpDxe"])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build.fv_modules(records + "\n" + records)
        with self.assertRaises(ValueError):
            build.fv_modules("EFI_FILE_NAME = /unexpected/entry.ffs")


if __name__ == "__main__":
    unittest.main()
