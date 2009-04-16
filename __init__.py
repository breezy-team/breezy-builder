# bzr-builder: a bzr plugin to constuct trees based on recipes
# Copyright 2009 Canonical Ltd.

# This program is free software: you can redistribute it and/or modify it 
# under the terms of the GNU General Public License version 3, as published 
# by the Free Software Foundation.

# This program is distributed in the hope that it will be useful, but 
# WITHOUT ANY WARRANTY; without even the implied warranties of 
# MERCHANTABILITY, SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR 
# PURPOSE.  See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along 
# with this program.  If not, see <http://www.gnu.org/licenses/>.

if __name__ == '__main__':
    import os
    import subprocess
    import sys
    dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugins")
    retcode = subprocess.call("bzr selftest -s bzrlib.plugins.builder",
            shell=True, env={"BZR_PLUGIN_PATH": dir})
    sys.exit(retcode)

import os
import subprocess

from debian_bundle import changelog

from bzrlib import (
        errors,
        trace,
        transport,
        )
from bzrlib.commands import Command, register_command
from bzrlib.option import Option

from bzrlib.plugins.builder.recipe import (
        build_manifest,
        build_tree,
        RecipeParser,
        resolve_revisions_until_different,
        )


class cmd_build(Command):
    """Build a tree based on a 'recipe'.

    Pass the name of the recipe file and the directory to work in.
    """
    takes_args = ["recipe_file", "working_directory"]
    takes_options = [
            Option('manifest', type=str, argname="path",
                   help="Path to write the manifest to."),
            Option('if-changed-from', type=str, argname="path",
                   help="Only build if the outcome would be different "
                        "to that specified in the specified manifest."),
                    ]

    def _write_manifest_to_path(self, path, base_branch):
        parent_dir = os.path.dirname(path)
        if parent_dir != '' and not os.path.exists(parent_dir):
            os.makedirs(parent_dir)
        manifest_f = open(path, 'wb')
        try:
            manifest_f.write(build_manifest(base_branch))
        finally:
            manifest_f.close()

    def _get_branch_from_recipe_file(self, recipe_file):
        recipe_transport = transport.get_transport(os.path.dirname(recipe_file))
        try:
            recipe_contents = recipe_transport.get_bytes(
                    os.path.basename(recipe_file))
        except errors.NoSuchFile:
            raise errors.BzrCommandError("Specified recipe does not exist: "
                    "%s" % recipe_file)
        parser = RecipeParser(recipe_contents, filename=recipe_file)
        return parser.parse()

    def _check_changed(self, base_branch, if_changed_from):
        old_manifest_transport = transport.get_transport(os.path.dirname(
                    if_changed_from))
        try:
            old_manifest_contents = old_manifest_transport.get_bytes(
                    os.path.basename(if_changed_from))
        except errors.NoSuchFile:
            raise errors.BzrCommandError("Specified previous manifest "
                    "does not exist: %s" % if_changed_from)
        old_recipe = RecipeParser(old_manifest_contents,
                filename=if_changed_from).parse()
        return resolve_revisions_until_different(base_branch,
                old_recipe)

    def run(self, recipe_file, working_directory, manifest=None,
            if_changed_from=None):
        base_branch = self._get_branch_from_recipe_file(recipe_file)
        if if_changed_from is not None:
            base_branch = self._check_changed(base_branch, if_changed_from)
            if base_branch is None:
                trace.note("Unchanged")
                return 0
        build_tree(base_branch, working_directory)
        if manifest is not None:
            self._write_manifest_to_path(manifest, base_branch)
        else:
            self._write_manifest_to_path(os.path.join(working_directory,
                        "bzr-builder.manifest"), base_branch)


register_command(cmd_build)


class cmd_dailydeb(cmd_build):
    """Build a deb based on a 'recipe'.
    """

    def run(self, recipe_file, working_directory, manifest=None,
            if_changed_from=None):
        base_branch = self._get_branch_from_recipe_file(recipe_file)
        if if_changed_from is not None:
            base_branch = self._check_changed(base_branch, if_changed_from)
            if base_branch is None:
                trace.note("Unchanged")
                return 0
        recipe_name = os.path.basename(recipe_file)
        if recipe_file.endswith(".recipe"):
            recipe_file = recipe_file[:-len(".recipe")]
        version = base_branch.deb_version
        if "-" in version:
            version = version[:version.rindex("-")]
        package_basedir = "%s-%s" % (recipe_file, version)
        if not os.path.exists(working_directory):
            os.makedirs(working_directory)
        package_dir = os.path.join(working_directory, package_basedir)
        build_tree(base_branch, package_dir)
        self._write_manifest_to_path(os.path.join(package_dir, "debian",
                    "bzr-builder.manifest"), base_branch)
        if manifest is not None:
            self._write_manifest_to_path(manifest, base_branch)


register_command(cmd_dailydeb)


def test_suite():
    from unittest import TestSuite
    from bzrlib.plugins.builder import tests
    result = TestSuite()
    result.addTest(tests.test_suite())
    return result
