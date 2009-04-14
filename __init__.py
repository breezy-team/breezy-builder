import os

from bzrlib import (
        errors,
        transport,
        )
from bzrlib.commands import Command, register_command

from bzrlib.plugins.builder.recipe import (
        build_tree,
        RecipeParser,
        )


class cmd_build(Command):
    """Build a tree based on a 'recipe'.

    Pass the name of the recipe file and the directory to work in.
    """
    takes_args = ["recipe_file", "working_directory"]

    def run(self, recipe_file, working_directory):
        recipe_transport = transport.get_transport(os.path.dirname(recipe_file))
        try:
            recipe_contents = recipe_transport.get_bytes(os.path.basename(recipe_file))
        except errors.NoSuchFile:
            raise errors.BzrCommandError("'%s' does not exist" % recipe_file)
        parser = RecipeParser(recipe_contents, filename=recipe_file)
        base_branch = parser.parse()
        build_tree(base_branch, working_directory)


register_command(cmd_build)


def test_suite():
    from unittest import TestSuite
    from bzrlib.plugins.builder import tests
    result = TestSuite()
    result.addTest(tests.test_suite())
    return result
