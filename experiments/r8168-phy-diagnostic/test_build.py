# SPDX-License-Identifier: MIT
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('r8168_build', Path(__file__).with_name('build.py'))
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def recipe(cc='aarch64-ark-linux-gcc -fuse-ld=bfd -ffile-prefix-map=/work/test=/usr/src/test'):
    return ('export PATH="/work/toolchain/bin:/work/build/tmp/hosttools"\n'
            'make -j 4 CC="' + cc + '" CXX="aarch64-ark-linux-gcc -x c++" '
            'LD="aarch64-ark-linux-ld.bfd " AR="aarch64-ark-linux-ar " '
            'OBJCOPY="aarch64-ark-linux-objcopy " "$@"\n')


class BuildTests(unittest.TestCase):
    def test_extracts_data_without_executing_other_shell(self):
        path, options = build.recipe_arguments(recipe() + 'touch /never-execute\n')
        self.assertEqual(path, '/work/toolchain/bin:/work/build/tmp/hosttools')
        self.assertIn('CXX=aarch64-ark-linux-gcc -x c++', options)
        self.assertEqual(len(options), 5)

    def test_rejects_compiler_shell_syntax(self):
        for syntax in (';id', '`id`', '$(id)', '\\n', '&&id'):
            with self.subTest(syntax=syntax), self.assertRaises(ValueError):
                build.recipe_arguments(recipe('aarch64-ark-linux-gcc ' + syntax))

    def test_rejects_wrong_compiler_or_duplicate(self):
        with self.assertRaises(ValueError):
            build.recipe_arguments(recipe('gcc'))
        with self.assertRaises(ValueError):
            build.recipe_arguments(recipe().replace('make -j 4 ', 'make -j 4 CC="aarch64-ark-linux-gcc" '))

    def test_rejects_ambiguous_or_missing_recipe(self):
        for text in ('', recipe() + recipe(), recipe().replace(' AR="aarch64-ark-linux-ar "', '')):
            with self.subTest(text=text), self.assertRaises(ValueError):
                build.recipe_arguments(text)

    def test_rejects_unpinned_path_or_shell_substitution(self):
        for value in ('/usr/bin', '/work/bin:','/work/$(id)', '/work/bin:/tmp/bin'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build.recipe_arguments(recipe().replace('/work/toolchain/bin:/work/build/tmp/hosttools', value))

    def test_existing_output_never_reaches_docker_or_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'private/r8168-diagnostic-build').mkdir(parents=True)
            with patch.object(build.Path, 'cwd', return_value=root), \
                 patch.object(build, 'audit', return_value=({}, '', [], 'hash')), \
                 patch.object(sys, 'argv', ['build.py']), \
                 patch.object(build.subprocess, 'check_output') as docker:
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    build.main()
                docker.assert_not_called()

    def test_symlinked_private_directory_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'elsewhere').mkdir()
            (root / 'private').symlink_to(root / 'elsewhere', target_is_directory=True)
            with patch.object(build.Path, 'cwd', return_value=root), \
                 patch.object(build, 'audit', return_value=({}, '', [], 'hash')), \
                 patch.object(sys, 'argv', ['build.py']):
                with self.assertRaisesRegex(ValueError, 'symlink'):
                    build.main()


if __name__ == '__main__':
    unittest.main()
