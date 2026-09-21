SUMMARY = "Grow the mounted JAJ NVMe APP ext4 filesystem on first boot"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://ark-grow-rootfs file://ark-grow-rootfs.service file://20-grow-rootfs.conf"
S = "${UNPACKDIR}"

inherit systemd features_check
REQUIRED_DISTRO_FEATURES = "systemd"
COMPATIBLE_MACHINE = "(ark-jaj-orin-nx)"
RDEPENDS:${PN} = "python3-core e2fsprogs-resize2fs"
SYSTEMD_SERVICE:${PN} = "ark-grow-rootfs.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

do_install() {
    install -d ${D}${libexecdir} ${D}${systemd_system_unitdir}
    sed -e 's,@RESIZE2FS@,${base_sbindir}/resize2fs,g' \
        ${S}/ark-grow-rootfs > ${D}${libexecdir}/ark-grow-rootfs
    chmod 0755 ${D}${libexecdir}/ark-grow-rootfs
    sed -e 's,@LIBEXECDIR@,${libexecdir},g' \
        ${S}/ark-grow-rootfs.service > ${D}${systemd_system_unitdir}/ark-grow-rootfs.service
    chmod 0644 ${D}${systemd_system_unitdir}/ark-grow-rootfs.service
    for unit in ark-os-ready ark-cuda-ready; do
        install -d ${D}${systemd_system_unitdir}/$unit.service.d
        install -m 0644 ${S}/20-grow-rootfs.conf ${D}${systemd_system_unitdir}/$unit.service.d/
    done
}

FILES:${PN} += "${libexecdir}/ark-grow-rootfs ${systemd_system_unitdir}"
