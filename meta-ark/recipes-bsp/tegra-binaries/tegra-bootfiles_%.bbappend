# SPDX-License-Identifier: MIT
# tegra-bootfiles uses shared vendor sources and has no do_unpack task. Fetch
# carrier files in their own recipe, then install them with the vendor inputs.
DEPENDS:append:ark-jaj-orin-nx = " ark-jaj-bct"

do_install:append:ark-jaj-orin-nx() {
    install -m 0644 ${RECIPE_SYSROOT}${datadir}/ark-jaj-bct/tegra234-*.dts* ${D}${datadir}/tegraflash/
}
