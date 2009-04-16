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

import os

from bzrlib import (
        errors,
        transport,
        )
from bzrlib.commands import Command, register_command
from bzrlib.option import Option

from bzrlib.plugins.builder.recipe import (
        build_manifest,
        build_tree,
        RecipeParser,
        )


class cmd_build(Command):
    """Build a tree based on a 'recipe'.

    Pass the name of the recipe file and the directory to work in.
    """
    takes_args = ["recipe_file", "working_directory"]
    takes_options = [
            Option('manifest', type=str, argname="path",
                   help="Path to write the manifest to"),
                    ]

    def run(self, recipe_file, working_directory, manifest=None):
        recipe_transport = transport.get_transport(os.path.dirname(recipe_file))
        try:
            recipe_contents = recipe_transport.get_bytes(os.path.basename(recipe_file))
        except errors.NoSuchFile:
            raise errors.BzrCommandError("'%s' does not exist" % recipe_file)
        parser = RecipeParser(recipe_contents, filename=recipe_file)
        base_branch = parser.parse()
        build_tree(base_branch, working_directory)
        if manifest is not None:
            parent_dir = os.path.dirname(manifest)
            if parent_dir != '':
                os.makedirs(parent_dir)
            manifest_f = open(manifest, 'wb')
            try:
                manifest_f.write(build_manifest(base_branch))
            finally:
                manifest_f.close()


register_command(cmd_build)


def test_suite():
    from unittest import TestSuite
    from bzrlib.plugins.builder import tests
    result = TestSuite()
    result.addTest(tests.test_suite())
    return result
