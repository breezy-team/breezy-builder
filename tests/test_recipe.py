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

import datetime
import os

from bzrlib import (
        errors,
        transport,
        workingtree,
        )
from bzrlib.tests import (
        TestCaseInTempDir,
        TestCaseWithTransport,
        )
from bzrlib.plugins.builder.recipe import (
        BaseRecipeBranch,
        build_manifest,
        build_tree,
        ensure_basedir,
        pull_or_branch,
        RecipeParser,
        RecipeBranch,
        RecipeParseError,
        resolve_revisions,
        )


class RecipeParserTests(TestCaseInTempDir):

    deb_version = "0.1-{revno}"
    basic_header = ("# bzr-builder format 0.1 deb-version "
            + deb_version +"\n")
    basic_header_and_branch = basic_header + "http://foo.org/\n"

    def get_recipe(self, recipe_text):
        return RecipeParser(recipe_text).parse()

    def assertParseError(self, line, char, problem, callable, *args,
            **kwargs):
        exc = self.assertRaises(RecipeParseError, callable, *args, **kwargs)
        self.assertEqual(problem, exc.problem)
        self.assertEqual(line, exc.line)
        self.assertEqual(char, exc.char)
        self.assertEqual("recipe", exc.filename)

    def check_recipe_branch(self, branch, name, url, revspec=None,
            num_child_branches=0, revid=None):
        self.assertEqual(name, branch.name)
        self.assertEqual(url, branch.url)
        self.assertEqual(revspec, branch.revspec)
        self.assertEqual(revid, branch.revid)
        self.assertEqual(num_child_branches, len(branch.child_branches))

    def check_base_recipe_branch(self, branch, url, revspec=None,
            num_child_branches=0, revid=None, deb_version=deb_version):
        self.check_recipe_branch(branch, None, url, revspec=revspec,
                num_child_branches=num_child_branches, revid=revid)
        self.assertEqual(deb_version, branch.deb_version)

    def test_parses_most_basic(self):
        self.get_recipe(self.basic_header_and_branch)

    def tests_rejects_non_comment_to_start(self):
        self.assertParseError(1, 1, "Expecting '#', got 'b'",
                self.get_recipe, "bzr-builder")

    def tests_rejects_wrong_format_definition(self):
        self.assertParseError(1, 3, "Expecting 'bzr-builder', "
                "got 'bzr-nothing'", self.get_recipe, "# bzr-nothing")

    def tests_rejects_no_format_definition(self):
        self.assertParseError(1, 3, "End of line while looking for "
                "'bzr-builder'", self.get_recipe, "# \n")

    def tests_rejects_no_format_definition_eof(self):
        self.assertParseError(1, 3, "End of line while looking for "
                "'bzr-builder'", self.get_recipe, "# ")

    def tests_rejects_wrong_format_version_marker(self):
        self.assertParseError(1, 15, "Expecting 'format', got 'aaaa'",
                self.get_recipe, "# bzr-builder aaaa")

    def test_rejects_invalid_format_version(self):
        self.assertParseError(1, 22, "Expecting a float, got 'foo'",
                self.get_recipe, "# bzr-builder format foo")

    def test_rejects_invalid_format_version2(self):
        self.assertParseError(1, 22, "Expecting a float, got '1.'",
                self.get_recipe, "# bzr-builder format 1.")

    def test_rejects_invalid_deb_version_marker(self):
        self.assertParseError(1, 24, "Expecting 'deb-version', "
                "got 'deb'", self.get_recipe, "# bzr-builder format 1 deb")

    def tests_rejects_no_deb_version_value(self):
        self.assertParseError(1, 35, "End of line while looking for "
                "a value for 'deb-version'", self.get_recipe,
                "# bzr-builder format 1 deb-version")

    def tests_rejects_extra_text_after_deb_version(self):
        self.assertParseError(1, 38, "Expecting the end of the line, "
                "got 'foo'", self.get_recipe,
                "# bzr-builder format 1 deb-version 1 foo")

    def tests_rejects_indented_base_branch(self):
        self.assertParseError(2, 3, "Not allowed to indent unless after "
                "a 'nest' line", self.get_recipe,
                self.basic_header + "  http://foo.org/")

    def tests_rejects_text_after_base_branch(self):
        self.assertParseError(2, 19, "Expecting the end of the line, "
                "got 'foo'", self.get_recipe,
                self.basic_header + "http://foo.org/ 2 foo")

    def tests_rejects_unknown_instruction(self):
        self.assertParseError(3, 1, "Expecting 'nest' or 'merge', "
                "got 'cat'", self.get_recipe,
                self.basic_header + "http://foo.org/\n" + "cat")

    def test_rejects_merge_no_name(self):
        self.assertParseError(3, 7, "End of line while looking for "
                "the branch id", self.get_recipe,
                self.basic_header_and_branch + "merge ")

    def test_rejects_merge_no_url(self):
        self.assertParseError(3, 11, "End of line while looking for "
                "the branch url", self.get_recipe,
                self.basic_header_and_branch + "merge foo ")

    def test_rejects_text_at_end_of_merge_line(self):
        self.assertParseError(3, 17, "Expecting the end of the line, "
                "got 'bar'", self.get_recipe,
                self.basic_header_and_branch + "merge foo url 2 bar")

    def test_rejects_nest_no_name(self):
        self.assertParseError(3, 6, "End of line while looking for "
                "the branch id", self.get_recipe,
                self.basic_header_and_branch + "nest ")

    def test_rejects_nest_no_url(self):
        self.assertParseError(3, 10, "End of line while looking for "
                "the branch url", self.get_recipe,
                self.basic_header_and_branch + "nest foo ")

    def test_rejects_nest_no_location(self):
        self.assertParseError(3, 14, "End of line while looking for "
                "the location to nest", self.get_recipe,
                self.basic_header_and_branch + "nest foo url ")

    def test_rejects_text_at_end_of_nest_line(self):
        self.assertParseError(3, 20, "Expecting the end of the line, "
                "got 'baz'", self.get_recipe,
                self.basic_header_and_branch + "nest foo url bar 2 baz")

    def test_rejects_indent_after_first_branch(self):
        self.assertParseError(3, 3, "Not allowed to indent unless after "
                "a 'nest' line", self.get_recipe,
                self.basic_header_and_branch + "  nest foo url bar")

    def test_rejects_indent_after_merge(self):
        self.assertParseError(4, 3, "Not allowed to indent unless after "
                "a 'nest' line", self.get_recipe,
                self.basic_header_and_branch + "merge foo url\n"
                + "  nest baz url bar")

    def test_rejects_tab_indent(self):
        self.assertParseError(4, 3, "Indents may not be done by tabs",
                self.get_recipe,
                self.basic_header_and_branch + "nest foo url bar\n"
                + "\t\tmerge baz url")

    def test_rejects_odd_space_indent(self):
        self.assertParseError(4, 2, "Indent not a multiple of two spaces",
                self.get_recipe,
                self.basic_header_and_branch + "nest foo url bar\n"
                + " merge baz url")

    def test_rejects_four_space_indent(self):
        self.assertParseError(4, 5, "Indented by more than two spaces "
                "at once", self.get_recipe,
                self.basic_header_and_branch + "nest foo url bar\n"
                + "    merge baz url")

    def test_rejects_empty_recipe(self):
        self.assertParseError(3, 1, "Empty recipe", self.get_recipe,
                self.basic_header)

    def test_builds_simplest_recipe(self):
        base_branch = self.get_recipe(self.basic_header_and_branch)
        self.check_base_recipe_branch(base_branch, "http://foo.org/")

    def test_builds_recipe_with_merge(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "merge bar http://bar.org")
        self.check_base_recipe_branch(base_branch, "http://foo.org/",
                num_child_branches=1)
        child_branch, location = base_branch.child_branches[0]
        self.assertEqual(None, location)
        self.check_recipe_branch(child_branch, "bar", "http://bar.org")

    def test_builds_recipe_with_nest(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest bar http://bar.org baz")
        self.check_base_recipe_branch(base_branch, "http://foo.org/",
                num_child_branches=1)
        child_branch, location = base_branch.child_branches[0]
        self.assertEqual("baz", location)
        self.check_recipe_branch(child_branch, "bar", "http://bar.org")

    def test_builds_recipe_with_nest_then_merge(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest bar http://bar.org baz\nmerge zam lp:zam")
        self.check_base_recipe_branch(base_branch, "http://foo.org/",
                num_child_branches=2)
        child_branch, location = base_branch.child_branches[0]
        self.assertEqual("baz", location)
        self.check_recipe_branch(child_branch, "bar", "http://bar.org")
        child_branch, location = base_branch.child_branches[1]
        self.assertEqual(None, location)
        self.check_recipe_branch(child_branch, "zam", "lp:zam")

    def test_builds_recipe_with_merge_then_nest(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "merge zam lp:zam\nnest bar http://bar.org baz")
        self.check_base_recipe_branch(base_branch, "http://foo.org/",
                num_child_branches=2)
        child_branch, location = base_branch.child_branches[0]
        self.assertEqual(None, location)
        self.check_recipe_branch(child_branch, "zam", "lp:zam")
        child_branch, location = base_branch.child_branches[1]
        self.assertEqual("baz", location)
        self.check_recipe_branch(child_branch, "bar", "http://bar.org")

    def test_builds_a_merge_in_to_a_nest(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest bar http://bar.org baz\n  merge zam lp:zam")
        self.check_base_recipe_branch(base_branch, "http://foo.org/",
                num_child_branches=1)
        child_branch, location = base_branch.child_branches[0]
        self.assertEqual("baz", location)
        self.check_recipe_branch(child_branch, "bar", "http://bar.org",
                num_child_branches=1)
        child_branch, location = child_branch.child_branches[0]
        self.assertEqual(None, location)
        self.check_recipe_branch(child_branch, "zam", "lp:zam")

    def tests_builds_nest_into_a_nest(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest bar http://bar.org baz\n  nest zam lp:zam zoo")
        self.check_base_recipe_branch(base_branch, "http://foo.org/",
                num_child_branches=1)
        child_branch, location = base_branch.child_branches[0]
        self.assertEqual("baz", location)
        self.check_recipe_branch(child_branch, "bar", "http://bar.org",
                num_child_branches=1)
        child_branch, location = child_branch.child_branches[0]
        self.assertEqual("zoo", location)
        self.check_recipe_branch(child_branch, "zam", "lp:zam")

    def tests_builds_recipe_with_revspecs(self):
        base_branch = self.get_recipe(self.basic_header
                + "http://foo.org/ revid:a\n"
                + "nest bar http://bar.org baz tag:b\n"
                + "merge zam lp:zam 2")
        self.check_base_recipe_branch(base_branch, "http://foo.org/",
                num_child_branches=2, revspec="revid:a")
        child_branch, location = base_branch.child_branches[0]
        self.assertEqual("baz", location)
        self.check_recipe_branch(child_branch, "bar", "http://bar.org",
                revspec="tag:b")
        child_branch, location = base_branch.child_branches[1]
        self.assertEqual(None, location)
        self.check_recipe_branch(child_branch, "zam", "lp:zam", revspec="2")


class BuildTreeTests(TestCaseWithTransport):

    def test_ensure_basedir(self):
        to_transport = transport.get_transport("a")
        ensure_basedir(to_transport)
        self.failUnlessExists("a")
        ensure_basedir(to_transport)
        self.failUnlessExists("a")
        e = self.assertRaises(errors.BzrCommandError, ensure_basedir,
                transport.get_transport("b/c"))
        self.assertTrue('Parent of "' in str(e))
        self.assertTrue('" does not exist.' in str(e))

    def test_build_tree_single_branch(self):
        source = self.make_branch_and_tree("source")
        revid = source.commit("one")
        base_branch = BaseRecipeBranch("source", "1")
        build_tree(base_branch, "target")
        self.failUnlessExists("target")
        tree = workingtree.WorkingTree.open("target")
        self.assertEqual(revid, tree.last_revision())
        self.assertEqual(revid, base_branch.revid)

    def test_build_tree_single_branch_dir_not_branch(self):
        source = self.make_branch_and_tree("source")
        revid = source.commit("one")
        # We just create the target as a directory
        os.mkdir("target")
        base_branch = BaseRecipeBranch("source", "1")
        build_tree(base_branch, "target")
        self.failUnlessExists("target")
        tree = workingtree.WorkingTree.open("target")
        self.assertEqual(revid, tree.last_revision())
        self.assertEqual(revid, base_branch.revid)

    def test_build_tree_single_branch_existing_branch(self):
        source = self.make_branch_and_tree("source")
        revid = source.commit("one")
        target = self.make_branch_and_tree("target")
        base_branch = BaseRecipeBranch("source", "1")
        build_tree(base_branch, "target")
        self.failUnlessExists("target")
        tree = workingtree.WorkingTree.open("target")
        self.assertEqual(revid, tree.last_revision())
        self.assertEqual(revid, base_branch.revid)

    def test_build_tree_nested(self):
        source1 = self.make_branch_and_tree("source1")
        self.build_tree(["source1/a"])
        source1.add(["a"])
        source1_rev_id = source1.commit("one")
        source2 = self.make_branch_and_tree("source2")
        self.build_tree(["source2/a"])
        source2.add(["a"])
        source2_rev_id = source2.commit("one")
        base_branch = BaseRecipeBranch("source1", "1")
        nested_branch = RecipeBranch("nested", "source2")
        base_branch.nest_branch("sub", nested_branch)
        build_tree(base_branch, "target")
        self.failUnlessExists("target")
        tree = workingtree.WorkingTree.open("target")
        self.assertEqual([source1_rev_id], tree.get_parent_ids())
        tree = workingtree.WorkingTree.open("target/sub")
        self.assertEqual([source2_rev_id], tree.get_parent_ids())
        self.assertEqual(source1_rev_id, base_branch.revid)
        self.assertEqual(source2_rev_id, nested_branch.revid)

    def test_build_tree_merged(self):
        source1 = self.make_branch_and_tree("source1")
        self.build_tree(["source1/a"])
        source1.add(["a"])
        source1_rev_id = source1.commit("one")
        source2 = source1.bzrdir.sprout("source2").open_workingtree()
        self.build_tree_contents([("source2/a", "other change")])
        source2_rev_id = source2.commit("one")
        base_branch = BaseRecipeBranch("source1", "1")
        merged_branch = RecipeBranch("merged", "source2")
        base_branch.merge_branch(merged_branch)
        build_tree(base_branch, "target")
        self.failUnlessExists("target")
        tree = workingtree.WorkingTree.open("target")
        last_revid = tree.last_revision()
        last_revtree = tree.branch.repository.revision_tree(last_revid)
        self.assertEqual([source1_rev_id, source2_rev_id],
                last_revtree.get_parent_ids())
        self.check_file_contents("target/a", "other change")
        self.assertEqual(source1_rev_id, base_branch.revid)
        self.assertEqual(source2_rev_id, merged_branch.revid)

    def test_build_tree_merge_twice(self):
        source1 = self.make_branch_and_tree("source1")
        self.build_tree(["source1/a"])
        source1.add(["a"])
        source1_rev_id = source1.commit("one")
        source2 = source1.bzrdir.sprout("source2").open_workingtree()
        self.build_tree_contents([("source2/a", "other change")])
        source2_rev_id = source2.commit("one")
        source3 = source2.bzrdir.sprout("source3").open_workingtree()
        self.build_tree_contents([("source3/a", "third change")])
        source3_rev_id = source3.commit("one")
        base_branch = BaseRecipeBranch("source1", "1")
        merged_branch1 = RecipeBranch("merged", "source2")
        base_branch.merge_branch(merged_branch1)
        merged_branch2 = RecipeBranch("merged2", "source3")
        base_branch.merge_branch(merged_branch2)
        build_tree(base_branch, "target")
        self.failUnlessExists("target")
        tree = workingtree.WorkingTree.open("target")
        last_revid = tree.last_revision()
        previous_revid = tree.branch.revision_history()[-2]
        last_revtree = tree.branch.repository.revision_tree(last_revid)
        previous_revtree = tree.branch.repository.revision_tree(previous_revid)
        self.assertEqual([previous_revid, source3_rev_id],
                last_revtree.get_parent_ids())
        self.assertEqual([source1_rev_id, source2_rev_id],
                previous_revtree.get_parent_ids())
        self.check_file_contents("target/a", "third change")
        self.assertEqual(source1_rev_id, base_branch.revid)
        self.assertEqual(source2_rev_id, merged_branch1.revid)
        self.assertEqual(source3_rev_id, merged_branch2.revid)

    def test_build_tree_merged_with_conflicts(self):
        source1 = self.make_branch_and_tree("source1")
        self.build_tree(["source1/a"])
        source1.add(["a"])
        source1_rev_id = source1.commit("one")
        source2 = source1.bzrdir.sprout("source2").open_workingtree()
        self.build_tree_contents([("source2/a", "other change\n")])
        source2_rev_id = source2.commit("one")
        self.build_tree_contents([("source1/a", "trunk change\n")])
        source1_rev_id = source1.commit("two")
        base_branch = BaseRecipeBranch("source1", "1")
        merged_branch = RecipeBranch("merged", "source2")
        base_branch.merge_branch(merged_branch)
        e = self.assertRaises(errors.BzrCommandError, build_tree,
                base_branch, "target")
        self.failUnlessExists("target")
        tree = workingtree.WorkingTree.open("target")
        self.assertEqual(source1_rev_id, tree.last_revision())
        self.assertEqual([source1_rev_id, source2_rev_id],
                tree.get_parent_ids())
        self.assertEqual(1, len(tree.conflicts()))
        conflict = tree.conflicts()[0]
        self.assertEqual("text conflict", conflict.typestring)
        self.assertEqual("a", conflict.path)
        self.check_file_contents("target/a", "<<<<<<< TREE\ntrunk change\n"
                "=======\nother change\n>>>>>>> MERGE-SOURCE\n")
        self.assertEqual(source1_rev_id, base_branch.revid)
        self.assertEqual(source2_rev_id, merged_branch.revid)

    def test_build_tree_with_revspecs(self):
        source1 = self.make_branch_and_tree("source1")
        self.build_tree(["source1/a"])
        source1.add(["a"])
        source1_rev_id = source1.commit("one")
        source2 = source1.bzrdir.sprout("source2").open_workingtree()
        self.build_tree_contents([("source2/a", "other change\n")])
        source2_rev_id = source2.commit("one")
        self.build_tree_contents([("source2/a", "unwanted change\n")])
        source2.commit("one")
        self.build_tree_contents([("source1/a", "unwanted trunk change\n")])
        source1.commit("two")
        base_branch = BaseRecipeBranch("source1", "1", revspec="1")
        merged_branch = RecipeBranch("merged", "source2", revspec="2")
        base_branch.merge_branch(merged_branch)
        build_tree(base_branch, "target")
        self.failUnlessExists("target")
        tree = workingtree.WorkingTree.open("target")
        last_revid = tree.last_revision()
        last_revtree = tree.branch.repository.revision_tree(last_revid)
        self.assertEqual([source1_rev_id, source2_rev_id],
                last_revtree.get_parent_ids())
        self.assertEqual(source1_rev_id, base_branch.revid)
        self.assertEqual(source2_rev_id, merged_branch.revid)

    def test_pull_or_branch_branch(self):
        source = self.make_branch_and_tree("source")
        source.lock_write()
        self.addCleanup(source.unlock)
        self.build_tree(["source/a"])
        source.add(["a"])
        rev_id = source.commit("one")
        source.branch.tags.set_tag("one", rev_id)
        to_transport = transport.get_transport("target")
        tree_to, br_to = pull_or_branch(None, None, source.branch,
                to_transport, rev_id)
        self.addCleanup(tree_to.unlock)
        self.addCleanup(br_to.unlock)
        self.assertEqual(rev_id, tree_to.last_revision())
        self.assertEqual(rev_id, br_to.last_revision())
        self.assertTrue(tree_to.is_locked())
        self.assertTrue(br_to.is_locked())
        self.assertEqual(rev_id, br_to.tags.lookup_tag("one"))

    def test_pull_or_branch_branch_in_no_trees_repo(self):
        """When in a no-trees repo we need to force a working tree"""
        repo = self.make_repository(".", shared=True)
        repo.set_make_working_trees(False)
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        source.add(["a"])
        rev_id = source.commit("one")
        source.branch.tags.set_tag("one", rev_id)
        to_transport = transport.get_transport("target")
        tree_to, br_to = pull_or_branch(None, None, source.branch,
                to_transport, rev_id)
        self.addCleanup(tree_to.unlock)
        self.addCleanup(br_to.unlock)
        self.assertEqual(rev_id, tree_to.last_revision())
        self.assertEqual(rev_id, br_to.last_revision())
        self.assertTrue(tree_to.is_locked())
        self.assertTrue(br_to.is_locked())
        self.assertEqual(rev_id, br_to.tags.lookup_tag("one"))

    def test_pull_or_branch_pull_with_tree(self):
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        source.add(["a"])
        first_rev_id = source.commit("one")
        source.branch.tags.set_tag("one", first_rev_id)
        to_transport = transport.get_transport("target")
        tree_to, br_to = pull_or_branch(None, None, source.branch,
                to_transport, first_rev_id)
        self.addCleanup(tree_to.unlock)
        self.addCleanup(br_to.unlock)
        self.build_tree(["source/b"])
        source.add(["b"])
        rev_id = source.commit("two")
        source.branch.tags.set_tag("one", rev_id)
        tree_to, br_to = pull_or_branch(tree_to, br_to, source.branch,
                to_transport, rev_id)
        self.assertEqual(rev_id, tree_to.last_revision())
        self.assertEqual(rev_id, br_to.last_revision())
        self.assertTrue(tree_to.is_locked())
        self.assertTrue(br_to.is_locked())
        # Changed tag isn't overwritten
        self.assertEqual(first_rev_id, br_to.tags.lookup_tag("one"))

    def test_pull_or_branch_pull_with_no_tree(self):
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        source.add(["a"])
        first_rev_id = source.commit("one")
        source.branch.tags.set_tag("one", first_rev_id)
        to_transport = transport.get_transport("target")
        tree_to, br_to = pull_or_branch(None, None, source.branch,
                to_transport, first_rev_id)
        tree_to.unlock()
        tree_to.bzrdir.destroy_workingtree()
        self.build_tree(["source/b"])
        source.add(["b"])
        rev_id = source.commit("two")
        source.branch.tags.set_tag("one", rev_id)
        tree_to, br_to = pull_or_branch(None, br_to, source.branch,
                to_transport, rev_id)
        self.addCleanup(tree_to.unlock)
        self.addCleanup(br_to.unlock)
        self.assertEqual(rev_id, tree_to.last_revision())
        self.assertEqual(rev_id, br_to.last_revision())
        self.assertTrue(tree_to.is_locked())
        self.assertTrue(br_to.is_locked())
        # Changed tag isn't overwritten
        self.assertEqual(first_rev_id, br_to.tags.lookup_tag("one"))

    def test_pull_or_branch_pull_with_conflicts(self):
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        source.add(["a"])
        first_rev_id = source.commit("one")
        source.branch.tags.set_tag("one", first_rev_id)
        to_transport = transport.get_transport("target")
        tree_to, br_to = pull_or_branch(None, None, source.branch,
                to_transport, first_rev_id)
        self.build_tree(["source/b"])
        self.build_tree_contents([("target/b", "other contents")])
        source.add(["b"])
        rev_id = source.commit("two")
        source.branch.tags.set_tag("one", rev_id)
        e = self.assertRaises(errors.BzrCommandError,
                pull_or_branch, tree_to, br_to, source.branch,
                to_transport, rev_id, accelerator_tree=source)
        self.assertEqual("Conflicts... aborting.", str(e))
        tree_to.unlock()
        br_to.unlock()
        tree_to = workingtree.WorkingTree.open("target")
        br_to = tree_to.branch
        self.assertEqual(rev_id, tree_to.last_revision())
        self.assertEqual(rev_id, br_to.last_revision())
        # Changed tag isn't overwritten
        self.assertEqual(first_rev_id, br_to.tags.lookup_tag("one"))
        self.assertEqual(1, len(tree_to.conflicts()))
        conflict = tree_to.conflicts()[0]
        self.assertEqual("duplicate", conflict.typestring)
        self.assertEqual("b.moved", conflict.path)
        self.assertEqual("b", conflict.conflict_path)


class ResolveRevisionsTests(TestCaseWithTransport):

    def test_unchanged(self):
        source =self.make_branch_and_tree("source")
        revid = source.commit("one")
        branch1 = BaseRecipeBranch("source", "{revno}", revspec="1")
        branch2 = BaseRecipeBranch("source", "{revno}",
                revspec="revid:%s" % revid)
        self.assertEqual(False, resolve_revisions(branch1,
                    if_changed_from=branch2))
        self.assertEqual("source", branch1.url)
        self.assertEqual(revid, branch1.revid)
        self.assertEqual("1", branch1.revspec)
        self.assertEqual("1", branch1.deb_version)

    def test_unchanged_not_explicit(self):
        source =self.make_branch_and_tree("source")
        revid = source.commit("one")
        branch1 = BaseRecipeBranch("source", "{revno}")
        branch2 = BaseRecipeBranch("source", "{revno}",
                revspec="revid:%s" % revid)
        self.assertEqual(False, resolve_revisions(branch1,
                    if_changed_from=branch2))
        self.assertEqual("source", branch1.url)
        self.assertEqual(revid, branch1.revid)
        self.assertEqual(None, branch1.revspec)
        self.assertEqual("1", branch1.deb_version)

    def test_changed(self):
        source =self.make_branch_and_tree("source")
        revid = source.commit("one")
        branch1 = BaseRecipeBranch("source", "{revno}", revspec="1")
        branch2 = BaseRecipeBranch("source", "{revno}", revspec="revid:foo")
        self.assertEqual(True, resolve_revisions(branch1,
                    if_changed_from=branch2))
        self.assertEqual("source", branch1.url)
        self.assertEqual(revid, branch1.revid)
        self.assertEqual("1", branch1.revspec)
        self.assertEqual("1", branch1.deb_version)

    def test_changed_shape(self):
        source =self.make_branch_and_tree("source")
        revid = source.commit("one")
        branch1 = BaseRecipeBranch("source", "{revno}", revspec="1")
        branch2 = BaseRecipeBranch("source", "{revno}",
                revspec="revid:%s" % revid)
        branch3 = RecipeBranch("nested", "source")
        branch1.nest_branch("foo", branch3)
        self.assertEqual(True, resolve_revisions(branch1,
                    if_changed_from=branch2))
        self.assertEqual("source", branch1.url)
        self.assertEqual(revid, branch1.revid)
        self.assertEqual("1", branch1.revspec)
        self.assertEqual("1", branch1.deb_version)

    def test_substitute(self):
        source =self.make_branch_and_tree("source")
        revid1 = source.commit("one")
        revid2 = source.commit("two")
        branch1 = BaseRecipeBranch("source",
                "{revno}-{revno:packaging}", revspec="1")
        branch2 = RecipeBranch("packaging", "source")
        branch1.nest_branch("debian", branch2)
        self.assertEqual(True, resolve_revisions(branch1))
        self.assertEqual("source", branch1.url)
        self.assertEqual(revid1, branch1.revid)
        self.assertEqual("1", branch1.revspec)
        self.assertEqual("1-2", branch1.deb_version)


class BuildManifestTests(TestCaseInTempDir):

    def test_simple_manifest(self):
        base_branch = BaseRecipeBranch("base_url", "1")
        base_branch.revid = "base_revid"
        manifest = build_manifest(base_branch)
        self.assertEqual("# bzr-builder format 0.1 deb-version 1\n"
                "base_url revid:base_revid\n", manifest)

    def test_complex_manifest(self):
        base_branch = BaseRecipeBranch("base_url", "2")
        base_branch.revid = "base_revid"
        nested_branch1 = RecipeBranch("nested1", "nested1_url")
        nested_branch1.revid = "nested1_revid"
        base_branch.nest_branch("nested", nested_branch1)
        nested_branch2 = RecipeBranch("nested2", "nested2_url")
        nested_branch2.revid = "nested2_revid"
        nested_branch1.nest_branch("nested2", nested_branch2)
        merged_branch = RecipeBranch("merged", "merged_url")
        merged_branch.revid = "merged_revid"
        base_branch.merge_branch(merged_branch)
        manifest = build_manifest(base_branch)
        self.assertEqual("# bzr-builder format 0.1 deb-version 2\n"
                "base_url revid:base_revid\n"
                "nest nested1 nested1_url nested revid:nested1_revid\n"
                "  nest nested2 nested2_url nested2 revid:nested2_revid\n"
                "merge merged merged_url revid:merged_revid\n", manifest)


class RecipeBranchTests(TestCaseInTempDir):

    def test_base_recipe_branch(self):
        base_branch = BaseRecipeBranch("base_url", "1", revspec="2")
        self.assertEqual(None, base_branch.name)
        self.assertEqual("base_url", base_branch.url)
        self.assertEqual("1", base_branch.deb_version)
        self.assertEqual("2", base_branch.revspec)
        self.assertEqual(0, len(base_branch.child_branches))
        self.assertEqual(None, base_branch.revid)

    def test_recipe_branch(self):
        branch = RecipeBranch("name", "url", revspec="2")
        self.assertEqual("name", branch.name)
        self.assertEqual("url", branch.url)
        self.assertEqual("2", branch.revspec)
        self.assertEqual(0, len(branch.child_branches))
        self.assertEqual(None, branch.revid)

    def test_different_shape_to(self):
        branch1 = BaseRecipeBranch("base_url", "1", revspec="2")
        branch2 = BaseRecipeBranch("base_url", "1", revspec="3")
        self.assertFalse(branch1.different_shape_to(branch2))
        branch2 = BaseRecipeBranch("base", "1", revspec="2")
        self.assertTrue(branch1.different_shape_to(branch2))
        branch2 = BaseRecipeBranch("base_url", "2", revspec="2")
        self.assertFalse(branch1.different_shape_to(branch2))
        rbranch1 = RecipeBranch("name", "other_url")
        rbranch2 = RecipeBranch("name2", "other_url")
        self.assertTrue(rbranch1.different_shape_to(rbranch2))
        rbranch2 = RecipeBranch("name", "other_url2")
        self.assertTrue(rbranch1.different_shape_to(rbranch2))

    def test_substitute_time(self):
        time = datetime.datetime.fromtimestamp(1)
        base_branch = BaseRecipeBranch("base_url", "1-{time}")
        base_branch.substitute_time(time)
        self.assertEqual("1-197001010100", base_branch.deb_version)
        base_branch.substitute_time(time)
        self.assertEqual("1-197001010100", base_branch.deb_version)

    def test_substitute_revno(self):
        base_branch = BaseRecipeBranch("base_url", "1")
        base_branch.substitute_revno(None, None)
        self.assertEqual("1", base_branch.deb_version)
        base_branch.substitute_revno(None, None)
        self.assertEqual("1", base_branch.deb_version)
        base_branch = BaseRecipeBranch("base_url", "{revno}")
        base_branch.substitute_revno(None, lambda: "2")
        self.assertEqual("2", base_branch.deb_version)
        base_branch.substitute_revno(None, lambda: "2")
        self.assertEqual("2", base_branch.deb_version)
        base_branch = BaseRecipeBranch("base_url", "{revno}")
        base_branch.substitute_revno("foo", None)
        self.assertEqual("{revno}", base_branch.deb_version)
        base_branch.substitute_revno("foo", None)
        self.assertEqual("{revno}", base_branch.deb_version)
        base_branch = BaseRecipeBranch("base_url", "{revno:foo}")
        base_branch.substitute_revno("foo", lambda: "3")
        self.assertEqual("3", base_branch.deb_version)
        base_branch.substitute_revno("foo", lambda: "3")
        self.assertEqual("3", base_branch.deb_version)
