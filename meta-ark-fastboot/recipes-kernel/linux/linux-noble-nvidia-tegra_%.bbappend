# The baseline retains the exact upstream source list and synchronous BPMP init.
ARK_BPMP_DEBUGFS_ASYNC ?= "0"
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI:append = "${@' file://0001-tegra-bpmp-optional-async-debugfs.patch' if d.getVar('ARK_BPMP_DEBUGFS_ASYNC') == '1' else ''}"

def ark_bpmp_verify_sources(d, patched=False):
    if d.getVar('ARK_BPMP_DEBUGFS_ASYNC') != '1':
        return
    import hashlib
    import os
    expected = {
        'drivers/firmware/tegra/bpmp.c': (
            'cf849c8aaea7d0c709bbba80fd2f1fa5c30b20b1b87e9c9afa205f38c47617f9'
            if patched else
            '9a197e986731682e54e2474078f1f7cc4d7369438cd6579752d6d7db711610c9'),
        'drivers/firmware/tegra/bpmp-debugfs.c':
            '081c627087704d1e200ea32bbed4c8cb84fa5d9d5a22ebc2a459fbb4b1d76a7e',
        'include/soc/tegra/bpmp.h':
            '611a4975295bc14f53290ab84e7e19a7b52170c54a802eed72312cd090181ac8',
    }
    for relative, digest in expected.items():
        path = os.path.join(d.getVar('S'), relative)
        try:
            with open(path, 'rb') as source:
                actual = hashlib.sha256(source.read()).hexdigest()
        except OSError as error:
            bb.fatal('ARK BPMP source verification failed for %s: %s' % (relative, error))
        if actual != digest:
            state = 'patched' if patched else 'original'
            bb.fatal('ARK BPMP %s source checksum mismatch: %s; re-audit before updating the source pin' % (state, relative))

python ark_bpmp_check_original() {
    ark_bpmp_verify_sources(d)
}

python ark_bpmp_check_patched() {
    ark_bpmp_verify_sources(d, patched=True)
}

# linux-yocto implements do_patch as shell; use independent Python hooks.
do_patch[prefuncs] += "${@'ark_bpmp_check_original' if d.getVar('ARK_BPMP_DEBUGFS_ASYNC') == '1' else ''}"
do_patch[postfuncs] += "${@'ark_bpmp_check_patched' if d.getVar('ARK_BPMP_DEBUGFS_ASYNC') == '1' else ''}"
