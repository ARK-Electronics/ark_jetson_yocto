# SPDX-License-Identifier: MIT
SUMMARY = "ARK Just a Jetson MB1 pinmux, GPIO and pad voltage, and MB2 carrier setup"
HOMEPAGE = "https://github.com/ARK-Electronics/ark_jetson_kernel"
LICENSE = "BSD-3-Clause"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/BSD-3-Clause;md5=550794465ba0ec5312d6919e203a55f9"

COMPATIBLE_MACHINE = "^ark-jaj-orin-nx$"
PACKAGE_ARCH = "${MACHINE_ARCH}"
INHIBIT_DEFAULT_DEPS = "1"
SRC_URI = " \
    file://tegra234-mb1-bct-pinmux-ark-jaj.dtsi \
    file://tegra234-mb1-bct-gpio-ark-jaj.dtsi \
    file://tegra234-mb1-bct-padvoltage-ark-jaj.dtsi \
    file://tegra234-mb2-bct-misc-ark-jaj.dts \
"
S = "${UNPACKDIR}"

do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    install -d ${D}${datadir}/ark-jaj-bct
    install -m 0644 ${S}/tegra234-*.dts* ${D}${datadir}/ark-jaj-bct/
}

FILES:${PN} = "${datadir}/ark-jaj-bct"
