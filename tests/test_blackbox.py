
from bzrlib import workingtree
from bzrlib.tests import (
        TestCaseWithTransport,
        )


class BlackboxBuilderTests(TestCaseWithTransport):

    def test_cmd_builder_exists(self):
        self.run_bzr("build --help")

    def test_cmd_builder_requires_recipe_file_argument(self):
        err = self.run_bzr("build", retcode=3)[1]
        self.assertEqual("bzr: ERROR: command 'build' requires argument "
                "RECIPE_FILE\n", err)

    def test_cmd_builder_requires_working_dir_argument(self):
        err = self.run_bzr("build recipe", retcode=3)[1]
        self.assertEqual("bzr: ERROR: command 'build' requires argument "
                "WORKING_DIRECTORY\n", err)

    def test_cmd_builder_nonexistant_recipe(self):
        err = self.run_bzr("build recipe working", retcode=3)[1]
        self.assertEqual("bzr: ERROR: 'recipe' does not exist\n", err)

    def test_cmd_builder_simple_recipe(self):
        self.build_tree_contents([("recipe", "# bzr-builder format 0.1 "
                    "deb-version 1\nsource\n")])
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        source.add(["a"])
        revid = source.commit("one")
        self.run_bzr("build recipe working")
        self.failUnlessExists("working/a")
        tree = workingtree.WorkingTree.open("working")
        self.assertEqual(revid, tree.last_revision())
