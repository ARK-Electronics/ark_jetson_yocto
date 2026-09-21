SUMMARY = "Provision an operator-supplied SSH public key without default credentials"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"
SRC_URI = "file://validate_public_key.py"
S = "${UNPACKDIR}"
ARK_SSH_PUBLIC_KEY ?= ""
# Root remains password-locked. OpenSSH permits only the supplied public key.
python do_install() {
    import importlib.util
    import os
    validator_path = os.path.join(d.getVar('UNPACKDIR'), 'validate_public_key.py')
    spec = importlib.util.spec_from_file_location('ark_validate_public_key', validator_path)
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    try:
        key = validator.validate_public_key(d.getVar('ARK_SSH_PUBLIC_KEY') or '')
    except ValueError as error:
        bb.fatal('Invalid ARK_SSH_PUBLIC_KEY: %s. Supply one real public key in ignored local.yml.' % error)
    root = d.getVar('D')
    home = root + d.getVar('ROOT_HOME') + '/.ssh'
    os.makedirs(home, mode=0o700, exist_ok=True)
    with open(home + '/authorized_keys', 'w') as f:
        f.write(key + '\n')
    os.chmod(home + '/authorized_keys', 0o600)
    config = root + d.getVar('sysconfdir') + '/ssh/sshd_config.d'
    os.makedirs(config, exist_ok=True)
    with open(config + '/20-ark-access.conf', 'w') as f:
        f.write('PermitRootLogin prohibit-password\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n')
}
FILES:${PN} = "${ROOT_HOME}/.ssh ${sysconfdir}/ssh/sshd_config.d/20-ark-access.conf"
RDEPENDS:${PN} = "openssh-sshd"
