#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise the real overlay and pinned OE4T extlinux code without BitBake."""
import copy
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import types
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DEPLOY = ROOT / "build/tmp/deploy/images/ark-jaj-orin-nx/devicetree"
BASE = Path(os.environ.get("ARK_NO_CAMERA_BASE_DTB", str(
    DEPLOY / "tegra234-ark-jaj-p3767-0000-super.dtb")))
CAMERA = Path(os.environ.get("ARK_NO_CAMERA_SENSOR_DTBO", str(
    DEPLOY / "tegra234-p3767-camera-p3768-imx219-dual.dtbo")))
MUX = "/bus@0/cam_i2cmux"


def tree_properties(path):
    """Read all FDT node/property bytes, ignoring layout and string-table order."""
    blob = path.read_bytes()
    magic, size, offset, strings, *_ = struct.unpack_from(">10I", blob)
    if magic != 0xd00dfeed or size > len(blob):
        raise ValueError("Invalid FDT header")
    nodes, stack = {}, []
    while offset < size:
        token, = struct.unpack_from(">I", blob, offset)
        offset += 4
        if token == 1:  # FDT_BEGIN_NODE
            end = blob.index(b"\0", offset)
            stack.append(blob[offset:end].decode("ascii"))
            nodes["/" + "/".join(stack[1:])] = {}
            offset = (end + 4) & ~3
        elif token == 2:  # FDT_END_NODE
            stack.pop()
        elif token == 3:  # FDT_PROP
            length, name_offset = struct.unpack_from(">II", blob, offset)
            offset += 8
            name_start = strings + name_offset
            name = blob[name_start:blob.index(b"\0", name_start)].decode("ascii")
            nodes["/" + "/".join(stack[1:])][name] = blob[offset:offset + length]
            offset = (offset + length + 3) & ~3
        elif token == 4:  # FDT_NOP
            pass
        elif token == 9:  # FDT_END
            if stack:
                raise ValueError("Unbalanced FDT nodes")
            return nodes
        else:
            raise ValueError("Unknown FDT token")
    raise ValueError("Missing FDT_END")


class Data:
    def __init__(self, values):
        self.values = values.copy()

    def getVar(self, name):
        return self.values.get(name, "")

    def setVar(self, name, value):
        self.values[name] = value


def fatal(message):
    raise RuntimeError(message)


class NoCameraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for tool in ("dtc", "fdtoverlay"):
            if not shutil.which(tool):
                raise RuntimeError("Required host tool: " + tool)
        for artifact in (BASE, CAMERA):
            if not artifact.is_file():
                raise RuntimeError("Missing artifact; set ARK_NO_CAMERA_BASE_DTB / "
                                   "ARK_NO_CAMERA_SENSOR_DTBO: " + str(artifact))
        cls.temporary = tempfile.TemporaryDirectory(prefix="ark-no-camera-test-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.work = Path(cls.temporary.name)
        cls.overlay = cls.work / "ark_no_csi.dtbo"
        subprocess.run(["dtc", "-I", "dts", "-O", "dtb", "-@", "-H", "epapr",
                        "-R", "0", "-b", "0", "-p", "0", "-o", str(cls.overlay),
                        str(HERE.parent / "files/ark_no_csi.dts")],
                       check=True, capture_output=True)
        cls.with_camera = cls.work / "camera-enabled.dtb"
        cls.merge(BASE, CAMERA, cls.with_camera)

    @staticmethod
    def merge(base, overlay, output):
        subprocess.run(["fdtoverlay", "-i", str(base), "-o", str(output), str(overlay)],
                       check=True, capture_output=True)

    def assert_only_camera_mux_changed(self, before_path, after_path):
        before = tree_properties(before_path)
        after = tree_properties(after_path)
        expected = copy.deepcopy(before)
        expected.setdefault(MUX, {})["status"] = b"disabled\0"
        self.assertEqual(after, expected)
        for node in ("/bus@0/pcie@14160000", "/bus@0/pcie@141e0000",
                     "/bus@0/gpu@17000000"):
            self.assertIn(node, before)
            self.assertEqual(after[node], before[node])
        self.assertEqual(after["/bus@0/pcie@141e0000"]["max-link-speed"],
                         struct.pack(">I", 2))

    def test_clean_dtb_adds_only_disabled_mux(self):
        self.assertNotIn(MUX, tree_properties(BASE))
        output = self.work / "clean-disabled.dtb"
        self.merge(BASE, self.overlay, output)
        self.assert_only_camera_mux_changed(BASE, output)

    def test_camera_enabled_dtb_disables_only_mux(self):
        nodes = tree_properties(self.with_camera)
        self.assertEqual(nodes[MUX].get("status"), b"okay\0")
        for path in (MUX + "/i2c@0/rbpcv2_imx219_a@10",
                     MUX + "/i2c@1/rbpcv2_imx219_c@10"):
            self.assertEqual(nodes[path]["compatible"], b"sony,imx219\0")
        output = self.work / "camera-disabled.dtb"
        self.merge(self.with_camera, self.overlay, output)
        self.assert_only_camera_mux_changed(self.with_camera, output)

    def test_reapplication_is_idempotent(self):
        once, twice = self.work / "once.dtb", self.work / "twice.dtb"
        self.merge(self.with_camera, self.overlay, once)
        self.merge(once, self.overlay, twice)
        self.assertEqual(tree_properties(once), tree_properties(twice))

    def test_native_extlinux_generation_and_install(self):
        # Execute pinned upstream functions, not a reimplementation of them.
        source = (ROOT / "repos/meta-tegra/classes-recipe/l4t-extlinux-config.bbclass").read_text()
        helper = source[source.index("def get_l4t_extlinux_compat_var("):
                        source.index("# Make compatible version")]
        body = source.split("python do_create_extlinux_config() {\n", 1)[1].split("\n}", 1)[0]
        namespace = {"bb": types.SimpleNamespace(
            fatal=fatal, error=fatal, warn=fatal,
            data=types.SimpleNamespace(createCopy=lambda data: Data(data.values)))}
        exec(compile(helper + "\ndef generate(d):\n" + body + "\n",
                     "l4t-extlinux-config.bbclass", "exec"), namespace)
        fragment = (ROOT / "kas/no-camera.yml").read_text()
        overlays = re.search(r'UBOOT_EXTLINUX_FDTOVERLAYS = "([^"]+)"', fragment).group(1)
        self.assertEqual(overlays, "ark_no_csi.dtbo")
        build = self.work / "extlinux-build"
        build.mkdir()
        values = {
            "UBOOT_EXTLINUX": "1", "WORKDIR": str(self.work),
            "UBOOT_EXTLINUX_LABELS": "primary", "OVERRIDES": "tegra234:ark-jaj-orin-nx",
            "UBOOT_EXTLINUX_CONFIG": str(build / "extlinux.conf"),
            "UBOOT_EXTLINUX_MENU_TITLE": "L4T boot options",
            "UBOOT_EXTLINUX_MENU_DESCRIPTION": "primary",
            "UBOOT_EXTLINUX_FDT": BASE.name,
            "UBOOT_EXTLINUX_KERNEL_IMAGE": "/boot/Image",
            "UBOOT_EXTLINUX_KERNEL_ARGS": "console=ttyTCU0,115200",
            "L4T_EXTLINUX_BASEDIR": "/boot",
        }
        namespace["generate"](Data(values))
        self.assertNotIn("OVERLAYS", (build / "extlinux.conf").read_text())
        values["UBOOT_EXTLINUX_FDTOVERLAYS"] = overlays
        namespace["generate"](Data(values))
        config = (build / "extlinux.conf").read_text()
        self.assertIn("\tFDT /boot/dtb/" + BASE.name + "\n", config)
        self.assertIn("\tOVERLAYS /boot/ark_no_csi.dtbo\n", config)
        self.assertNotIn("FDTOVERLAYS", config)
        shutil.copyfile(BASE, build / BASE.name)
        shutil.copyfile(self.overlay, build / self.overlay.name)
        (build / "Image").write_bytes(b"test-kernel-placeholder")
        install_source = (ROOT / "repos/meta-tegra/recipes-bsp/uefi/l4t-launcher-extlinux.bb").read_text()
        install_body = install_source.split("do_install() {\n", 1)[1].split("\n}", 1)[0]
        destination = self.work / "installed"
        environment = dict(values, PATH=os.environ["PATH"], B=str(build), D=str(destination),
                           KERNEL_IMAGETYPE="Image", L4T_UBOOT_EXTLINUX_FDT=BASE.name,
                           L4T_UBOOT_EXTLINUX_EXTRA_FDTS="", INITRAMFS_IMAGE="",
                           INITRAMFS_IMAGE_BUNDLE="")
        subprocess.run(["bash", "-eu", "-c", install_body], cwd=build,
                       env=environment, check=True, capture_output=True)
        self.assertEqual((destination / "boot/ark_no_csi.dtbo").read_bytes(),
                         self.overlay.read_bytes())
        self.assertEqual((destination / "boot/extlinux/extlinux.conf").read_text(), config)


class NoCameraDependencyTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("ARK_NO_CAMERA_TASK_GRAPH"),
                         "Set ARK_NO_CAMERA_TASK_GRAPH to the combined variant's bitbake -g output")
    def test_generated_flash_and_extlinux_dependencies(self):
        # Inspect BitBake's resolved graph: existing deploy files must not hide
        # a missing provider dependency, as they did in the original variant.
        graph = Path(os.environ["ARK_NO_CAMERA_TASK_GRAPH"]).read_text()
        edges = set(re.findall(r'"([^"\n]+)" -> "([^"\n]+)"', graph))
        image = "ark-headless-image.do_image_tegraflash_tar"
        stock = "nvidia-kernel-oot-dtbo"
        custom = "ark-no-camera-overlay"
        required = {
            (image, stock + ".do_populate_sysroot"),
            (image, custom + ".do_populate_sysroot"),
            ("l4t-launcher-extlinux.do_copy_dtb_overlays", stock + ".do_populate_sysroot"),
            ("l4t-launcher-extlinux.do_prepare_recipe_sysroot", custom + ".do_populate_sysroot"),
        }
        self.assertFalse(required - edges, "Missing resolved task edges: " + repr(required - edges))
        for recipe in (stock, custom):
            self.assertIn('"' + recipe + '.do_deploy"', graph)
            self.assertIn((recipe + ".do_populate_sysroot", recipe + ".do_install"), edges)
            self.assertIn((recipe + ".do_install", recipe + ".do_compile"), edges)


if __name__ == "__main__":
    unittest.main()
