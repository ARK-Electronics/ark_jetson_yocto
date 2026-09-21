# SPDX-License-Identifier: MIT
SUMMARY = "ARK Just a Jetson carrier device tree for Orin NX 16GB"
HOMEPAGE = "https://github.com/ARK-Electronics/ark_jetson_kernel"
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/GPL-2.0-only;md5=801f80980d171dd6425610833a22dbe6"

inherit tegra-devicetree

COMPATIBLE_MACHINE = "^ark-jaj-orin-nx$"
SRC_URI = " \
    file://tegra234-ark-jaj-p3767-0000-super.dts \
    file://ark-JAJ-overrides.dtsi \
    file://tegra234-dcb-p3737-0000-p3701-0000-hdmi.dtsi \
    file://ark_boot_order.dts \
"
DT_FILES = "tegra234-ark-jaj-p3767-0000-super.dts ark_boot_order.dts"
DT_RESERVED_MAP = "0"
DT_PADDING_SIZE = "0"
