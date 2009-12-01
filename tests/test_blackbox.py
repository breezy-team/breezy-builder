# bzr-builter: a bzr plugin to constuct trees based on recipes
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

from bzrlib import workingtree
from bzrlib.tests import (
        TestCaseWithTransport,
        )


class BlackboxBuilderTests(TestCaseWithTransport):

    def setUp(self):
        super(BlackboxBuilderTests, self).setUp()
        # Replace DEBEMAIL and DEBFULLNAME so that they are known values
        # for the changelog checks.
        self._captureVar("DEBEMAIL", "maint@maint.org")
        self._captureVar("DEBFULLNAME", "M. Maintainer")

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
        self.assertEqual("bzr: ERROR: Specified recipe does not exist: "
                "recipe\n", err)

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
        self.failUnlessExists("working/bzr-builder.manifest")
        self.check_file_contents("working/bzr-builder.manifest",
                "# bzr-builder format 0.1 deb-version 1\nsource revid:%s\n"
                % revid)

    def test_cmd_builder_manifest(self):
        self.build_tree_contents([("recipe", "# bzr-builder format 0.1 "
                    "deb-version 1\nsource\n")])
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        source.add(["a"])
        revid = source.commit("one")
        self.run_bzr("build recipe working --manifest manifest")
        self.failUnlessExists("working/a")
        self.failUnlessExists("manifest")
        self.check_file_contents("manifest", "# bzr-builder format 0.1 "
                    "deb-version 1\nsource revid:%s\n" % revid)

    def test_cmd_builder_if_changed_does_not_exist(self):
        self.build_tree_contents([("recipe", "# bzr-builder format 0.1 "
                    "deb-version 1\nsource\n")])
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        source.add(["a"])
        revid = source.commit("one")
        out, err = self.run_bzr("build recipe working "
                "--if-changed-from manifest")

    def test_cmd_builder_if_changed_not_changed(self):
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        source.add(["a"])
        revid = source.commit("one")
        self.build_tree_contents([("recipe", "# bzr-builder format 0.1 "
                    "deb-version 1\nsource 1\n")])
        self.build_tree_contents([("old-manifest", "# bzr-builder format 0.1 "
                    "deb-version 1\nsource revid:%s\n" % revid)])
        out, err = self.run_bzr("build recipe working --manifest manifest "
                "--if-changed-from old-manifest")
        self.failIfExists("working")
        self.failIfExists("manifest")
        self.assertEqual("Unchanged\n", err)

    def test_cmd_builder_if_changed_changed(self):
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        source.add(["a"])
        revid = source.commit("one")
        self.build_tree_contents([("recipe", "# bzr-builder format 0.1 "
                    "deb-version 1\nsource 1\n")])
        self.build_tree_contents([("old-manifest", "# bzr-builder format 0.1 "
                    "deb-version 1\nsource revid:foo\n")])
        out, err = self.run_bzr("build recipe working --manifest manifest "
                "--if-changed-from old-manifest")
        self.failUnlessExists("working/a")
        self.failUnlessExists("manifest")
        self.check_file_contents("manifest", "# bzr-builder format 0.1 "
                    "deb-version 1\nsource revid:%s\n" % revid)

    def test_cmd_dailydeb(self):
        #TODO: define a test feature for debuild and require it here.
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a", "source/debian/"])
        self.build_tree_contents([("source/debian/rules",
                    "#!/usr/bin/make -f\nclean:\n"),
                ("source/debian/control",
                    "Source: foo\nMaintainer: maint maint@maint.org\n")])
        source.add(["a", "debian/", "debian/rules", "debian/control"])
        revid = source.commit("one")
        self.build_tree_contents([("test.recipe", "# bzr-builder format 0.1 "
                    "deb-version 1\nsource 1\n")])
        out, err = self.run_bzr("dailydeb test.recipe working "
                "--manifest manifest --package foo")
        self.failIfExists("working/a")
        package_root = "working/foo-1/"
        self.failUnlessExists(os.path.join(package_root, "a"))
        self.failUnlessExists(os.path.join(package_root,
                    "debian/bzr-builder.manifest"))
        self.failUnlessExists("manifest")
        self.check_file_contents("manifest", "# bzr-builder format 0.1 "
                    "deb-version 1\nsource revid:%s\n" % revid)
        self.check_file_contents(os.path.join(package_root,
                    "debian/bzr-builder.manifest"),
                    "# bzr-builder format 0.1 deb-version 1\nsource revid:%s\n"
                    % revid)
        cl_path = os.path.join(package_root, "debian/changelog")
        self.failUnlessExists(cl_path)
        cl_f = open(cl_path)
        try:
            line = cl_f.readline()
            self.assertEqual("foo (1) jaunty; urgency=low\n", line)
        finally:
            cl_f.close()

    def test_cmd_dailydeb_no_work_dir(self):
        #TODO: define a test feature for debuild and require it here.
        if getattr(self, "permit_dir", None) is not None:
            self.permit_dir('/') # Allow the made working dir to be accessed.
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a", "source/debian/"])
        self.build_tree_contents([("source/debian/rules",
                    "#!/usr/bin/make -f\nclean:\n"),
                ("source/debian/control",
                    "Source: foo\nMaintainer: maint maint@maint.org\n")])
        source.add(["a", "debian/", "debian/rules", "debian/control"])
        revid = source.commit("one")
        self.build_tree_contents([("test.recipe", "# bzr-builder format 0.1 "
                    "deb-version 1\nsource 1\n")])
        out, err = self.run_bzr("dailydeb test.recipe "
                "--manifest manifest --package foo")

    def test_cmd_dailydeb_if_changed_from_non_existant(self):
        #TODO: define a test feature for debuild and require it here.
        if getattr(self, "permit_dir", None) is not None:
            self.permit_dir('/') # Allow the made working dir to be accessed.
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a", "source/debian/"])
        self.build_tree_contents([("source/debian/rules",
                    "#!/usr/bin/make -f\nclean:\n"),
                ("source/debian/control",
                    "Source: foo\nMaintainer: maint maint@maint.org\n")])
        source.add(["a", "debian/", "debian/rules", "debian/control"])
        revid = source.commit("one")
        self.build_tree_contents([("test.recipe", "# bzr-builder format 0.1 "
                    "deb-version 1\nsource 1\n")])
        out, err = self.run_bzr("dailydeb test.recipe "
                "--manifest manifest --package foo --if-changed-from bar")

    def test_cmd_dailydeb_with_package_from_changelog(self):
        #TODO: define a test feature for debuild and require it here.
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a", "source/debian/"])
        cl_contents = ("package (0.1-1) unstable; urgency=low\n  * foo\n"
                    " -- maint <maint@maint.org>  Tue, 04 Aug 2009 "
                    "10:03:10 +0100\n")
        self.build_tree_contents([("source/debian/rules",
                    "#!/usr/bin/make -f\nclean:\n"),
                ("source/debian/control",
                    "Source: package\nMaintainer: maint maint@maint.org\n"),
                ("source/debian/changelog", cl_contents)])
        source.add(["a", "debian/", "debian/rules", "debian/control",
                "debian/changelog"])
        revid = source.commit("one")
        self.build_tree_contents([("test.recipe", "# bzr-builder format 0.1 "
                    "deb-version 1\nsource 1\n")])
        out, err = self.run_bzr("dailydeb test.recipe "
                "--manifest manifest --if-changed-from bar working")
        new_cl_contents = ("package (1) unstable; urgency=low\n\n"
                "  * Auto build.\n\n -- M. Maintainer <maint@maint.org>  ")
        f = open("working/test-1/debian/changelog")
        try:
            actual_cl_contents = f.read()
        finally:
            f.close()
        self.assertEqual(new_cl_contents,
                actual_cl_contents[:len(new_cl_contents)])
