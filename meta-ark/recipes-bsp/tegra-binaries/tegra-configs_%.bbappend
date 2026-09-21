# SPDX-License-Identifier: MIT
# Keep the NVIDIA modules, libraries and variant marker, but do not preload
# display DRM before R39's GPU power policy on the headless JAJ image.
FILESEXTRAPATHS:prepend:ark-jaj-orin-nx := "${THISDIR}/tegra-configs/ark-jaj:"
PACKAGE_ARCH:ark-jaj-orin-nx = "${MACHINE_ARCH}"
LICENSE:append:ark-jaj-orin-nx = " & MIT"
LIC_FILES_CHKSUM:append:ark-jaj-orin-nx = " file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"
