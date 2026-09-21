#!/usr/bin/env python3
"""Reproduce the bounded r8168 diagnostic against an existing, pinned build."""
# SPDX-License-Identifier: MIT
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
RECIPE = Path('build/tmp/work/ark_jaj_orin_nx-ark-linux/nvidia-kernel-oot/39.2.1')
SOURCE = RECIPE / 'sources/nvidia-kernel-oot-39.2.1'
DRIVER = SOURCE / 'nvidia-oot/drivers/net/ethernet/realtek/r8168'
KERNEL = Path('build/tmp/work-shared/ark-jaj-orin-nx/kernel-build-artifacts')
RELEASE = '6.8.12-l4t-r39.2.1-1021.21'
PATCHES = (
    ('0001-phy-observations.patch', 'ad5349075fc178598c27c512dd2f2c0d29dac16350e24d65f442a0932473fa92'),
    ('0002-pre-reset-mcu-observations.patch', '8cee52fc89bfc02ad2d5bd17a58cf8a7398b32699d567207ecc1e5392a29a244'),
)
RESULT_SOURCE = 'd2620f52319bd36098fa2f36b0f5fc779989a72f852f0d1531b086ddfedf40a2'
SAFE_TOKEN = re.compile(r'[A-Za-z0-9_./+=,:-]+\Z')
COMPILERS = {'CC': 'aarch64-ark-linux-gcc', 'CXX': 'aarch64-ark-linux-gcc',
             'LD': 'aarch64-ark-linux-ld.bfd', 'AR': 'aarch64-ark-linux-ar',
             'OBJCOPY': 'aarch64-ark-linux-objcopy'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recipe_arguments(text):
    """Read only known data fields; never source/eval the generated shell script."""
    paths = [line for line in text.splitlines() if line.startswith('export PATH=')]
    makes = [line.strip() for line in text.splitlines() if line.strip().startswith('make -j ')]
    if len(paths) != 1 or len(makes) != 1:
        raise ValueError('Unsupported generated recipe command layout')
    words = shlex.split(paths[0])
    if len(words) != 2 or words[0] != 'export':
        raise ValueError('Unsupported PATH export')
    path = words[1].removeprefix('PATH=')
    if any(not p.startswith('/work/') or not SAFE_TOKEN.fullmatch(p) for p in path.split(':')):
        raise ValueError('Unsupported PATH value')
    options = {}
    for token in shlex.split(makes[0]):
        name, sep, value = token.partition('=')
        if name not in COMPILERS or not sep:
            continue
        if re.search(r'[$`\\;&|<>()\n\r]', value):
            raise ValueError('Shell syntax is forbidden in compiler assignments')
        args = shlex.split(value)
        if name in options or not args or args[0] != COMPILERS[name]:
            raise ValueError('Unsupported compiler assignment: ' + name)
        if any(not SAFE_TOKEN.fullmatch(arg) for arg in args):
            raise ValueError('Shell syntax is forbidden in compiler arguments')
        options[name] = name + '=' + ' '.join(args)
    if options.keys() != COMPILERS.keys():
        raise ValueError('Missing compiler assignments')
    return path, [options[key] for key in COMPILERS]


def audit(repo):
    pins = json.loads((HERE / 'inputs.json').read_text())
    for relative, expected in pins.items():
        path = repo / relative
        if path.is_symlink() or not path.is_file() or sha(path) != expected:
            raise ValueError('Missing or changed pinned input: ' + relative)
    if (repo / KERNEL / 'include/config/kernel.release').read_text().strip() != RELEASE:
        raise ValueError('Wrong kernel release')
    for name, expected in PATCHES:
        if sha(HERE / name) != expected:
            raise ValueError('Changed diagnostic patch: ' + name)
    run = repo / RECIPE / 'temp/run.do_compile'
    path, options = recipe_arguments(run.read_text())
    return pins, path, options, sha(run)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-name', default='r8168-diagnostic-build',
                        help='new directory name below repository private/; never overwritten')
    parser.add_argument('--check', action='store_true', help='audit inputs only; do not create output or build')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.output_name):
        raise ValueError('Output name must be a simple directory name')
    repo = Path.cwd().resolve()
    if any(c in str(repo) for c in ':,\n\r'):
        raise ValueError('Unsupported repository path for Docker bind mount')
    pins, path, options, recipe_hash = audit(repo)
    if args.check:
        print('Pinned source, kernel, patches and generated compiler arguments verified.')
        return 0
    private = repo / 'private'
    if private.is_symlink():
        raise ValueError('private/ must not be a symlink')
    private.mkdir(exist_ok=True)
    output = private / args.output_name
    if output.exists() or output.is_symlink():
        raise ValueError('Output already exists; choose a new --output-name')
    image = os.environ.get('ARK_BUILDER_IMAGE', f'ark-jetson-yocto-builder:wrynose-{os.getuid()}-{os.getgid()}')
    image_id = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], text=True).strip()
    output.mkdir()  # atomic refusal if another invocation created it
    module = output / 'module'
    module.mkdir()
    for item in (repo / DRIVER).iterdir():
        if item.name == 'Makefile' or (item.suffix in ('.c', '.h') and not item.name.endswith('.mod.c')):
            if item.is_symlink() or not item.is_file():
                raise ValueError('Unsupported source entry: ' + item.name)
            shutil.copy2(item, module / item.name)
    with (output / 'patch.log').open('x') as log:
        for name, _ in PATCHES:
            subprocess.run(['patch', '--batch', '--fuzz=0', '-p6', '-i', str(HERE / name)],
                           cwd=module, stdout=log, stderr=subprocess.STDOUT, check=True)
    if sha(module / 'r8168_n.c') != RESULT_SOURCE:
        raise ValueError('Unexpected patched source')
    container_output = '/work/private/' + args.output_name
    source = '/work/' + str(SOURCE)
    command = ['make', '-C', '/work/' + str(KERNEL), '-j2', 'ARCH=arm64',
               'CROSS_COMPILE=aarch64-ark-linux-', *options, 'M=' + container_output + '/module',
               f'KCPPFLAGS=-I{source}/out/nvidia-conftest -I{source}/nvidia-oot/include',
               'KCFLAGS=-Werror -Wmissing-prototypes', 'modules']
    docker = ['docker', 'run', '--rm', '--init', '--network=none', '--user', f'{os.getuid()}:{os.getgid()}',
              '-v', f'{repo}:/work:ro', '-v', f'{output}:{container_output}:rw', '-w', '/work',
              '--entrypoint', '/usr/bin/env', image_id,
              '-u', 'CFLAGS', '-u', 'CPPFLAGS', '-u', 'CXXFLAGS', '-u', 'LDFLAGS', '-u', 'KBUILD_OUTPUT',
              'PATH=' + path, 'ARCH=arm64', 'CROSS_COMPILE=aarch64-ark-linux-', *command]
    report = {'inputs': pins, 'recipe_script_sha256': recipe_hash, 'builder_image': image_id,
              'make_argv': command, 'docker_argv': docker, 'PATH': path,
              'patched_source_sha256': RESULT_SOURCE, 'kernel_release': RELEASE}
    manifest = output / 'manifest.json'
    manifest.write_text(json.dumps(report, indent=2) + '\n')
    with (output / 'build.log').open('x') as log:
        result = subprocess.run(docker, stdout=log, stderr=subprocess.STDOUT)
    report['build_exit'] = result.returncode
    if result.returncode == 0:
        built = module / 'r8168.ko'
        report.update(module_sha256=sha(built), module_bytes=built.stat().st_size)
    manifest.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Build exit {result.returncode}; output: {output}')
    return result.returncode


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        sys.exit(1)
