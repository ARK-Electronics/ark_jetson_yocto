# SPDX-License-Identifier: MIT
SUMMARY = "Optional JAJ camera mux disable overlay for camera-less benches"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

inherit devicetree

# This supplements NVIDIA's virtual/dtbo provider. Replacing that provider
# would omit firmware carveout, OP-TEE and SKU overlays from flash packaging.
# Only kas/no-camera.yml adds this recipe to the boot-file dependencies.
PROVIDES = ""
COMPATIBLE_MACHINE = "^ark-jaj-orin-nx$"
SRC_URI = "file://ark_no_csi.dts"
DT_FILES = "ark_no_csi.dts"
KERNEL_INCLUDE = ""
DT_RESERVED_MAP = "0"
