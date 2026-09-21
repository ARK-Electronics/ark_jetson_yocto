SUMMARY = "Provision an operator-supplied SSH public key without default credentials"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"
S = "${UNPACKDIR}"
ARK_SSH_PUBLIC_KEY ?= ""
# Root remains password-locked. OpenSSH permits only the supplied public key.
python do_install() {
    import os
    key = (d.getVar('ARK_SSH_PUBLIC_KEY') or '').strip()
    if not key or '\n' in key or not key.startswith(('ssh-ed25519 ', 'ssh-rsa ', 'ecdsa-sha2-')):
        bb.fatal('Set ARK_SSH_PUBLIC_KEY to one SSH public key in ignored local.yml before building')
    root = d.getVar('D')
    home = root + '/home/root/.ssh'
    os.makedirs(home, mode=0o700, exist_ok=True)
    with open(home + '/authorized_keys', 'w') as f:
        f.write(key + '\n')
    os.chmod(home + '/authorized_keys', 0o600)
    config = root + d.getVar('sysconfdir') + '/ssh/sshd_config.d'
    os.makedirs(config, exist_ok=True)
    with open(config + '/20-ark-access.conf', 'w') as f:
        f.write('PermitRootLogin prohibit-password\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n')
}
FILES:${PN} = "/home/root/.ssh ${sysconfdir}/ssh/sshd_config.d/20-ark-access.conf"
RDEPENDS:${PN} = "openssh-sshd"
