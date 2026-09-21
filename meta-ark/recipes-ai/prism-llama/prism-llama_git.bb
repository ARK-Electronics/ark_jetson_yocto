SUMMARY = "PrismML llama.cpp CUDA runtime for Bonsai 2 on Jetson Orin"
HOMEPAGE = "https://github.com/PrismML-Eng/llama.cpp"
DESCRIPTION = "Pinned Prism runtime with llama-bench, llama-cli and the HTTP API server. Model weights are provisioned separately."
LICENSE = "MIT & BSD-2-Clause & Unlicense & PD"
LIC_FILES_CHKSUM = " \
    file://LICENSE;md5=223b26b3c1143120c87e2b13111d3e99 \
    file://vendor/cpp-httplib/LICENSE;md5=1321bdf796c67e3a8ab8e352dd81474b \
    file://vendor/hash/xxhash/LICENSE;md5=13be6b481ff5616f77dda971191bb29b \
    file://vendor/hash/rotate-bits/LICENSE.md;md5=bcdfbfcc0d644320ff435b1acd3627e7 \
    file://vendor/hash/sha256/LICENSE;md5=9023e9d96f2f04557d35e682b39ffd60 \
    file://vendor/hash/sha1/sha1.c;beginline=1;endline=4;md5=dc1dcce51b7ccfcfeb0d22ca7f9c7b6d \
    file://vendor/sheredom/subprocess.h;beginline=6;endline=31;md5=2f28eeefd99ea31587161405acf5ecef \
    file://vendor/miniaudio/miniaudio.h;beginline=95817;endline=95864;md5=1f09aeb340535c2bbf8158f6397a94f0 \
    file://vendor/stb/stb_image.h;beginline=7950;endline=7988;md5=8fe7e3ded5234a7f06ded2806ea59b6b \
"

# The same source as the native Ubuntu benchmark: prism-b10683-d8f26ee.
SRC_URI = "git://github.com/PrismML-Eng/llama.cpp.git;protocol=https;nobranch=1"
SRCREV = "d8f26eec76da6d09bb708bcba51ef64b8cd868a3"
PV = "0.2.0+prism10683+git"

COMPATIBLE_MACHINE = "(tegra234)"

inherit cmake cuda pkgconfig

DEPENDS = "openssl"
# Avoid the cuda class's full optional CUDA library set for this runtime.
# cuda-cudart also stages the CUDA driver, compiler headers and CCCL.
CUDA_DEPENDS = "cuda-cudart cuda-crt libcublas ${CUDA_NATIVEDEPS}"
CUDA_ARCHITECTURES = "87"
OECMAKE_C_FLAGS_RELEASE = "-O3 -DNDEBUG"
OECMAKE_CXX_FLAGS_RELEASE = "-O3 -DNDEBUG"
OECMAKE_TARGET_COMPILE = "llama-bench llama-server llama-cli"

EXTRA_OECMAKE = " \
    -DBUILD_SHARED_LIBS=ON \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_SKIP_RPATH=ON \
    -DGGML_CCACHE=OFF \
    -DGGML_NATIVE=OFF \
    -DGGML_CPU_ARM_ARCH=armv8.2-a+dotprod+fp16 \
    -DGGML_BACKEND_DL=OFF \
    -DGGML_CUDA=ON \
    -DGGML_CUDA_GRAPHS=ON \
    -DGGML_CUDA_NCCL=OFF \
    -DGGML_CUDA_CUB_3DOT2=OFF \
    -DLLAMA_BUILD_COMMON=ON \
    -DLLAMA_BUILD_TOOLS=ON \
    -DLLAMA_BUILD_SERVER=ON \
    -DLLAMA_BUILD_TESTS=OFF \
    -DLLAMA_BUILD_EXAMPLES=OFF \
    -DLLAMA_BUILD_APP=OFF \
    -DLLAMA_BUILD_UI=OFF \
    -DLLAMA_USE_PREBUILT_UI=OFF \
    -DLLAMA_OPENSSL=ON \
"

# This Prism revision ignores LLAMA_CURL; its API uses cpp-httplib/OpenSSL.
# Upstream CUDA unconditionally uses -use_fast_math, as in the Ubuntu build.
# Do not add host -ffast-math or change the CUDA arithmetic for comparison.

do_install() {
    install -d ${D}${bindir} ${D}${libdir}
    for tool in llama-bench llama-server llama-cli; do
        install -m 0755 ${B}/bin/$tool ${D}${bindir}/
    done
    # Upstream's global install also expects tools we deliberately do not build.
    # Keep all built runtime libraries and SONAME links; omit linker-only links.
    for library in ${B}/bin/lib*.so*; do
        case "$library" in
            *.so) [ ! -L "$library" ] || continue ;;
        esac
        cp -a --no-preserve=ownership "$library" ${D}${libdir}/
    done

    install -d ${D}${datadir}/licenses/${BPN}
    install -m 0644 ${S}/LICENSE ${D}${datadir}/licenses/${BPN}/LICENSE
    (
        cat ${S}/vendor/cpp-httplib/LICENSE
        cat ${S}/vendor/hash/xxhash/LICENSE
        cat ${S}/vendor/hash/rotate-bits/LICENSE.md
        cat ${S}/vendor/hash/sha256/LICENSE
        sed -n '1,4p' ${S}/vendor/hash/sha1/sha1.c
        sed -n '1,8p' ${S}/vendor/nlohmann/json.hpp
        sed -n '6,31p' ${S}/vendor/sheredom/subprocess.h
        sed -n '95817,95864p' ${S}/vendor/miniaudio/miniaudio.h
        sed -n '7950,7988p' ${S}/vendor/stb/stb_image.h
    ) > ${D}${datadir}/licenses/${BPN}/THIRD-PARTY-NOTICES
}

# The three libllama-*-impl.so files are real, unversioned runtime libraries.
# No development linker symlinks or headers are installed by this recipe.
FILES_SOLIBSDEV = ""
FILES:${PN} += "${libdir}/lib*.so ${datadir}/licenses/${BPN}"
RRECOMMENDS:${PN} += "ca-certificates"
