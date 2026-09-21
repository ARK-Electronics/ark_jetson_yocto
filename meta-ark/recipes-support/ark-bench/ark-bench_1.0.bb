SUMMARY = "ARK CPU/CUDA correctness probes, bounded benchmarks and uptime milestones"
DESCRIPTION = "Native CUDA integer computation with full result verification and separate initialization/steady-state timing, fixed-data OpenSSL SHA-256 throughput, and distinct multi-user/CUDA-ready console markers."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://CMakeLists.txt \
    file://bench-common.h \
    file://cpu-bench.cpp \
    file://cuda-bench.cu \
    file://ark-readiness \
    file://ark-os-ready.service \
    file://ark-cuda-ready.service \
"
S = "${UNPACKDIR}"

inherit cmake cuda systemd features_check

COMPATIBLE_MACHINE = "(tegra234)"
REQUIRED_DISTRO_FEATURES = "systemd"
# Follow meta-tegra's compiler/sysroot integration, without staging every CUDA
# math library for a program that only calls the runtime API.
CUDA_DEPENDS = "cuda-cudart ${CUDA_NATIVEDEPS}"
DEPENDS += "openssl cuda-crt"
OECMAKE_CUDA_ARCHITECTURES = "87-real"
EXTRA_OECMAKE += "-DARK_ENABLE_CUDA=ON"

RDEPENDS:${PN} += "tegra-nvpmodel"
SYSTEMD_SERVICE:${PN} = "ark-os-ready.service ark-cuda-ready.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

do_install:append() {
    install -d ${D}${libexecdir} ${D}${systemd_system_unitdir}
    install -m 0755 ${S}/ark-readiness ${D}${libexecdir}/ark-readiness
    sed -i -e 's,/usr/bin/,${bindir}/,g' ${D}${libexecdir}/ark-readiness
    for unit in ark-os-ready.service ark-cuda-ready.service; do
        sed -e 's,/usr/libexec/,${libexecdir}/,g' ${S}/$unit > ${D}${systemd_system_unitdir}/$unit
        chmod 0644 ${D}${systemd_system_unitdir}/$unit
    done
}

FILES:${PN} += "${libexecdir}/ark-readiness ${systemd_system_unitdir}"
