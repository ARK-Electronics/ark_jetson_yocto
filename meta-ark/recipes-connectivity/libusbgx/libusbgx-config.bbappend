FILESEXTRAPATHS:prepend := "${THISDIR}/${BPN}:"

SRC_URI:append:ark-jaj-orin-nx = " file://0001-stable-usb-network-addresses.patch"
RDEPENDS:${PN}:append:ark-jaj-orin-nx = " coreutils"
