FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append:ark-jaj-orin-nx = " file://10-ark-usb-dhcp.conf"

do_install:append:ark-jaj-orin-nx() {
    install -d ${D}${sysconfdir}/systemd/network/70-l4tbr0.network.d
    install -m 0644 ${UNPACKDIR}/10-ark-usb-dhcp.conf ${D}${sysconfdir}/systemd/network/70-l4tbr0.network.d/
}

FILES:${PN}:append:ark-jaj-orin-nx = " ${sysconfdir}/systemd/network/70-l4tbr0.network.d"
