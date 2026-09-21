SUMMARY = "Ethernet DHCP configuration for headless ARK Jetson"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"
SRC_URI = "file://80-ethernet.network"
S = "${UNPACKDIR}"
do_install() {
    install -d ${D}${sysconfdir}/systemd/network
    install -m 0644 ${S}/80-ethernet.network ${D}${sysconfdir}/systemd/network/
}
RDEPENDS:${PN} = "systemd-networkd systemd-resolved"
