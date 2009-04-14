
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
        build_tree,
        ensure_basedir,
        pull_or_branch,
        RecipeParser,
        RecipeBranch,
        RecipeParseError,
        )


class RecipeParserTests(TestCaseInTempDir):

    basic_header = "# bzr-builder format 0.1 deb-version 0.1-{revision}\n"
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
        self.assertParseError(1, 36, "End of line while looking for "
                "a value for 'deb-version'", self.get_recipe,
                "# bzr-builder format 1 deb-version ")

    def tests_rejects_extra_text_after_deb_version(self):
        self.assertParseError(1, 38, "Expecting the end of the line, "
                "got 'foo'", self.get_recipe,
                "# bzr-builder format 1 deb-version 1 foo")

    def tests_rejects_indented_base_branch(self):
        self.assertParseError(2, 3, "Not allowed to indent unless after "
                "a 'nest' line", self.get_recipe,
                self.basic_header + "  http://foo.org/")

    def tests_rejects_text_after_base_branch(self):
        self.assertParseError(2, 17, "Expecting the end of the line, "
                "got 'foo'", self.get_recipe,
                self.basic_header + "http://foo.org/ foo")

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
        self.assertParseError(3, 15, "Expecting the end of the line, "
                "got 'bar'", self.get_recipe,
                self.basic_header_and_branch + "merge foo url bar")

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
        self.assertParseError(3, 18, "Expecting the end of the line, "
                "got 'baz'", self.get_recipe,
                self.basic_header_and_branch + "nest foo url bar baz")

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
        self.assertEqual("", base_branch.name)
        self.assertEqual("http://foo.org/", base_branch.url)
        self.assertEqual(0, len(base_branch.child_branches))

    def test_builds_recipe_with_merge(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "merge bar http://bar.org")
        self.assertEqual("", base_branch.name)
        self.assertEqual("http://foo.org/", base_branch.url)
        self.assertEqual(1, len(base_branch.child_branches))
        child_branch, location = base_branch.child_branches[0]
        self.assertEqual(None, location)
        self.assertEqual("bar", child_branch.name)
        self.assertEqual("http://bar.org", child_branch.url)
        self.assertEqual(0, len(child_branch.child_branches))

    def test_builds_recipe_with_nest(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest bar http://bar.org baz")
        self.assertEqual("", base_branch.name)
        self.assertEqual("http://foo.org/", base_branch.url)
        self.assertEqual(1, len(base_branch.child_branches))
        child_branch, location = base_branch.child_branches[0]
        self.assertEqual("baz", location)
        self.assertEqual("bar", child_branch.name)
        self.assertEqual("http://bar.org", child_branch.url)
        self.assertEqual(0, len(child_branch.child_branches))

    def test_builds_recipe_with_nest_then_merge(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest bar http://bar.org baz\nmerge zam lp:zam")
        self.assertEqual("", base_branch.name)
        self.assertEqual("http://foo.org/", base_branch.url)
        self.assertEqual(2, len(base_branch.child_branches))
        child_branch, location = base_branch.child_branches[0]
        self.assertEqual("baz", location)
        self.assertEqual("bar", child_branch.name)
        self.assertEqual("http://bar.org", child_branch.url)
        self.assertEqual(0, len(child_branch.child_branches))
        child_branch, location = base_branch.child_branches[1]
        self.assertEqual(None, location)
        self.assertEqual("zam", child_branch.name)
        self.assertEqual("lp:zam", child_branch.url)
        self.assertEqual(0, len(child_branch.child_branches))

    def test_builds_recipe_with_merge_then_nest(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "merge zam lp:zam\nnest bar http://bar.org baz")
        self.assertEqual("", base_branch.name)
        self.assertEqual("http://foo.org/", base_branch.url)
        self.assertEqual(2, len(base_branch.child_branches))
        child_branch, location = base_branch.child_branches[0]
        self.assertEqual(None, location)
        self.assertEqual("zam", child_branch.name)
        self.assertEqual("lp:zam", child_branch.url)
        self.assertEqual(0, len(child_branch.child_branches))
        child_branch, location = base_branch.child_branches[1]
        self.assertEqual("baz", location)
        self.assertEqual("bar", child_branch.name)
        self.assertEqual("http://bar.org", child_branch.url)
        self.assertEqual(0, len(child_branch.child_branches))

    def test_builds_a_merge_in_to_a_nest(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest bar http://bar.org baz\n  merge zam lp:zam")
        self.assertEqual("", base_branch.name)
        self.assertEqual("http://foo.org/", base_branch.url)
        self.assertEqual(1, len(base_branch.child_branches))
        child_branch, location = base_branch.child_branches[0]
        self.assertEqual("baz", location)
        self.assertEqual("bar", child_branch.name)
        self.assertEqual("http://bar.org", child_branch.url)
        self.assertEqual(1, len(child_branch.child_branches))
        child_branch, location = child_branch.child_branches[0]
        self.assertEqual(None, location)
        self.assertEqual("zam", child_branch.name)
        self.assertEqual("lp:zam", child_branch.url)
        self.assertEqual(0, len(child_branch.child_branches))

    def tests_builds_nest_into_a_nest(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest bar http://bar.org baz\n  nest zam lp:zam zoo")
        self.assertEqual("", base_branch.name)
        self.assertEqual("http://foo.org/", base_branch.url)
        self.assertEqual(1, len(base_branch.child_branches))
        child_branch, location = base_branch.child_branches[0]
        self.assertEqual("baz", location)
        self.assertEqual("bar", child_branch.name)
        self.assertEqual("http://bar.org", child_branch.url)
        self.assertEqual(1, len(child_branch.child_branches))
        child_branch, location = child_branch.child_branches[0]
        self.assertEqual("zoo", location)
        self.assertEqual("zam", child_branch.name)
        self.assertEqual("lp:zam", child_branch.url)
        self.assertEqual(0, len(child_branch.child_branches))


class BuildTreeTests(TestCaseWithTransport):

    def test_ensure_basedir(self):
        ensure_basedir("a")
        self.failUnlessExists("a")
        ensure_basedir("a")
        self.failUnlessExists("a")
        e = self.assertRaises(errors.BzrCommandError, ensure_basedir,
                "b/c")
        self.assertEqual('Parent of "b/c" does not exist.', str(e))

    def test_build_tree_single_branch(self):
        source = self.make_branch_and_tree("source")
        revid = source.commit("one")
        base_branch = RecipeBranch("", "source")
        build_tree(base_branch, "target")
        self.failUnlessExists("target")
        tree = workingtree.WorkingTree.open("target")
        self.assertEqual(revid, tree.last_revision())

    def test_build_tree_single_branch_dir_not_branch(self):
        source = self.make_branch_and_tree("source")
        revid = source.commit("one")
        # We just create the target as a directory
        os.mkdir("target")
        base_branch = RecipeBranch("", "source")
        build_tree(base_branch, "target")
        self.failUnlessExists("target")
        tree = workingtree.WorkingTree.open("target")
        self.assertEqual(revid, tree.last_revision())

    def test_build_tree_single_branch_existing_branch(self):
        source = self.make_branch_and_tree("source")
        revid = source.commit("one")
        target = self.make_branch_and_tree("target")
        base_branch = RecipeBranch("", "source")
        build_tree(base_branch, "target")
        self.failUnlessExists("target")
        tree = workingtree.WorkingTree.open("target")
        self.assertEqual(revid, tree.last_revision())

    def test_build_tree_nested(self):
        source1 = self.make_branch_and_tree("source1")
        self.build_tree(["source1/a"])
        source1.add(["a"])
        source1_rev_id = source1.commit("one")
        source2 = self.make_branch_and_tree("source2")
        self.build_tree(["source2/a"])
        source2.add(["a"])
        source2_rev_id = source2.commit("one")
        base_branch = RecipeBranch("", "source1")
        nested_branch = RecipeBranch("nested", "source2")
        base_branch.nest_branch("sub", nested_branch)
        build_tree(base_branch, "target")
        self.failUnlessExists("target")
        tree = workingtree.WorkingTree.open("target")
        last_revid = tree.last_revision()
        last_revtree = tree.branch.repository.revision_tree(last_revid)
        self.assertEqual([source1_rev_id], last_revtree.get_parent_ids())
        tree = workingtree.WorkingTree.open("target/sub")
        self.assertEqual(source2_rev_id, tree.last_revision())

    def test_build_tree_merged(self):
        source1 = self.make_branch_and_tree("source1")
        self.build_tree(["source1/a"])
        source1.add(["a"])
        source1_rev_id = source1.commit("one")
        source2 = source1.bzrdir.sprout("source2").open_workingtree()
        self.build_tree_contents([("source2/a", "other change")])
        source2_rev_id = source2.commit("one")
        base_branch = RecipeBranch("", "source1")
        merged_branch = RecipeBranch("nested", "source2")
        base_branch.merge_branch(merged_branch)
        build_tree(base_branch, "target")
        self.failUnlessExists("target")
        tree = workingtree.WorkingTree.open("target")
        last_revid = tree.last_revision()
        last_revtree = tree.branch.repository.revision_tree(last_revid)
        self.assertEqual([source1_rev_id, source2_rev_id],
                last_revtree.get_parent_ids())
        self.check_file_contents("target/a", "other change")

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
        base_branch = RecipeBranch("", "source1")
        merged_branch = RecipeBranch("nested", "source2")
        base_branch.merge_branch(merged_branch)
        merged_branch = RecipeBranch("nested2", "source3")
        base_branch.merge_branch(merged_branch)
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
        base_branch = RecipeBranch("", "source1")
        merged_branch = RecipeBranch("nested", "source2")
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
                to_transport, None, [])
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
                to_transport, None, [])
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
                to_transport, None, [])
        self.addCleanup(tree_to.unlock)
        self.addCleanup(br_to.unlock)
        self.build_tree(["source/b"])
        source.add(["b"])
        rev_id = source.commit("two")
        source.branch.tags.set_tag("one", rev_id)
        tree_to, br_to = pull_or_branch(tree_to, br_to, source.branch,
                to_transport, source, [])
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
                to_transport, None, [])
        tree_to.unlock()
        tree_to.bzrdir.destroy_workingtree()
        self.build_tree(["source/b"])
        source.add(["b"])
        rev_id = source.commit("two")
        source.branch.tags.set_tag("one", rev_id)
        tree_to, br_to = pull_or_branch(None, br_to, source.branch,
                to_transport, source, [])
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
                to_transport, None, [])
        self.build_tree(["source/b"])
        self.build_tree_contents([("target/b", "other contents")])
        source.add(["b"])
        rev_id = source.commit("two")
        source.branch.tags.set_tag("one", rev_id)
        e = self.assertRaises(errors.BzrCommandError,
                pull_or_branch, tree_to, br_to, source.branch,
                to_transport, source, [])
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
