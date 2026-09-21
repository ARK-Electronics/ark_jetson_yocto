# SPDX-License-Identifier: MIT
FILESEXTRAPATHS:prepend:ark-jaj-orin-nx := "${THISDIR}/tegra-nvpower/ark-jaj:"
SRC_URI:append:ark-jaj-orin-nx = " file://20-ark-jaj-gpu-policy.conf"

do_install:append:ark-jaj-orin-nx() {
    # R39's native GPU udev handler calls an Ubuntu-only wrapper which OE4T
    # does not install. Its only operation after waiting for the config is
    # this same native nvpmodel call. The config is already in the image.
    # Keep the handler's failure check before its first GPU power-on write.
    if [ "$(grep -Fc '"!:/etc/systemd/nvpmodel.sh"' ${D}${libexecdir}/nvpower.sh)" -ne 1 ]; then
        bbfatal "Unaudited NVIDIA GPU policy helper: expected exactly one nvpmodel.sh command"
    fi
    sed -i -e 's,"!:/etc/systemd/nvpmodel.sh","!:${sbindir}/nvpmodel -f ${sysconfdir}/nvpmodel.conf </dev/null",' \
        ${D}${libexecdir}/nvpower.sh

    install -d ${D}${systemd_system_unitdir}/nvpower.service.d
    sed -e 's,@SH@,${base_bindir}/sh,g' \
        -e 's,@UDEVADM@,${base_bindir}/udevadm,g' \
        ${UNPACKDIR}/20-ark-jaj-gpu-policy.conf \
        > ${D}${systemd_system_unitdir}/nvpower.service.d/20-ark-jaj-gpu-policy.conf
    chmod 0644 ${D}${systemd_system_unitdir}/nvpower.service.d/20-ark-jaj-gpu-policy.conf
}

FILES:${PN}:append:ark-jaj-orin-nx = " ${systemd_system_unitdir}/nvpower.service.d/20-ark-jaj-gpu-policy.conf"
# nvpower uses the binary/config from -base. The image explicitly installs
# tegra-nvpmodel's service, which already depends on nvpower; avoid a cycle.
RDEPENDS:${PN}:remove:ark-jaj-orin-nx = "tegra-nvpmodel"
RDEPENDS:${PN}:append:ark-jaj-orin-nx = " udev tegra-nvpmodel-base"
LICENSE:append:ark-jaj-orin-nx = " & MIT"
LIC_FILES_CHKSUM:append:ark-jaj-orin-nx = " file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"
