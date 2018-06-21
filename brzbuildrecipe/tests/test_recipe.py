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

from breezy import (
        errors,
        transport,
        workingtree,
        )
from breezy.tests import (
        TestCaseInTempDir,
        TestCaseWithTransport,
        )
from ..recipe import (
        BaseRecipeBranch,
        build_tree,
        ensure_basedir,
        InstructionParseError,
        ForbiddenInstructionError,
        MERGE_INSTRUCTION,
        NEST_INSTRUCTION,
        NEST_PART_INSTRUCTION,
        pull_or_branch,
        RecipeParser,
        RecipeBranch,
        RecipeParseError,
        RUN_INSTRUCTION,
        SAFE_INSTRUCTIONS,
        USAGE,
        )

class RecipeParserTests(TestCaseInTempDir):

    deb_version = "0.1-{revno}"
    basic_header = ("# bzr-builder format 0.3 deb-version "
            + deb_version +"\n")
    basic_branch = "http://foo.org/"
    basic_header_and_branch = basic_header + basic_branch + "\n"

    def get_recipe(self, recipe_text, **kwargs):
        return RecipeParser(recipe_text).parse(**kwargs)

    def assertParseError(self, line, char, problem, callable, *args,
            **kwargs):
        exc = self.assertRaises(RecipeParseError, callable, *args, **kwargs)
        self.assertEqual(problem, exc.problem)
        self.assertEqual(line, exc.line)
        self.assertEqual(char, exc.char)
        self.assertEqual("recipe", exc.filename)
        return exc

    def assertInstructionParseError(self, line, char, problem, instruction,
            callable, *args, **kwargs):
        exc = self.assertParseError(line, char, problem, callable, *args,
                **kwargs)
        self.assertIsInstance(exc, InstructionParseError),
        self.assertEqual(USAGE[instruction], exc.usage)

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

    def test_parses_missing_deb_version(self):
        header = "# bzr-builder format 0.3\n"
        branch = "http://foo.org/\n"
        self.get_recipe(header + branch)

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

    def test_unknown_format_version(self):
        self.assertParseError(1, 22, "Unknown format: '10000'",
                self.get_recipe, "# bzr-builder format 10000 deb-version 1\n")

    def test_rejects_invalid_deb_version_marker(self):
        self.assertParseError(1, 26, "Expecting 'deb-version', "
                "got 'deb'", self.get_recipe, "# bzr-builder format 0.1 deb")

    def tests_rejects_no_deb_version_value(self):
        self.assertParseError(1, 37, "End of line while looking for "
                "a value for 'deb-version'", self.get_recipe,
                "# bzr-builder format 0.1 deb-version")

    def tests_rejects_extra_text_after_deb_version(self):
        self.assertParseError(1, 40, "Expecting the end of the line, "
                "got 'foo'", self.get_recipe,
                "# bzr-builder format 0.1 deb-version 1 foo")

    def tests_rejects_indented_base_branch(self):
        self.assertParseError(2, 3, "Not allowed to indent unless after "
                "a 'nest' line", self.get_recipe,
                self.basic_header + "  http://foo.org/")

    def tests_rejects_text_after_base_branch(self):
        self.assertParseError(2, 19, "Expecting the end of the line, "
                "got 'foo'", self.get_recipe,
                self.basic_header + "http://foo.org/ 2 foo")

    def tests_rejects_unknown_instruction(self):
        self.assertParseError(3, 1, "Expecting 'merge', 'nest', 'nest-part' "
                "or 'run', got 'cat'", self.get_recipe,
                self.basic_header + "http://foo.org/\n" + "cat")

    def test_rejects_merge_no_name(self):
        self.assertInstructionParseError(3, 7, "End of line while looking for "
                "the branch id", MERGE_INSTRUCTION, self.get_recipe,
                self.basic_header_and_branch + "merge ")

    def test_rejects_merge_no_name_no_space(self):
        self.assertInstructionParseError(3, 6, "End of line while looking for "
                "the branch id", MERGE_INSTRUCTION, self.get_recipe,
                self.basic_header_and_branch + "merge")

    def test_rejects_merge_no_url(self):
        self.assertInstructionParseError(3, 11, "End of line while looking for"
                " the branch url", MERGE_INSTRUCTION, self.get_recipe,
                self.basic_header_and_branch + "merge foo ")

    def test_rejects_text_at_end_of_merge_line(self):
        self.assertInstructionParseError(3, 17,
                "Expecting the end of the line, got 'bar'",
                MERGE_INSTRUCTION, self.get_recipe,
                self.basic_header_and_branch + "merge foo url 2 bar")

    def test_rejects_nest_part_no_name(self):
        self.assertInstructionParseError(3, 11, "End of line while looking for"
                " the branch id", NEST_PART_INSTRUCTION, self.get_recipe,
                self.basic_header_and_branch + "nest-part ")

    def test_rejects_nest_part_no_url(self):
        self.assertInstructionParseError(3, 15, "End of line while looking for"
                " the branch url", NEST_PART_INSTRUCTION, self.get_recipe,
                self.basic_header_and_branch + "nest-part foo ")

    def test_rejects_nest_part_no_subpath(self):
        self.assertInstructionParseError(3, 22, "End of line while looking for"
                " the subpath to merge", NEST_PART_INSTRUCTION,
                self.get_recipe,
                self.basic_header_and_branch + "nest-part foo url:// ")

    def test_rejects_nest_part_no_subpath_no_space(self):
        self.assertInstructionParseError(3, 21, "End of line while looking for"
                " the subpath to merge", NEST_PART_INSTRUCTION,
                self.get_recipe,
                self.basic_header_and_branch + "nest-part foo url://")

    def test_rejects_nest_no_name(self):
        self.assertInstructionParseError(3, 6, "End of line while looking for"
                " the branch id", NEST_INSTRUCTION, self.get_recipe,
                self.basic_header_and_branch + "nest ")

    def test_rejects_nest_no_url(self):
        self.assertInstructionParseError(3, 10,
            "End of line while looking for the branch url",
            NEST_INSTRUCTION, self.get_recipe,
            self.basic_header_and_branch + "nest foo ")

    def test_rejects_nest_no_location(self):
        self.assertInstructionParseError(3, 14,
                "End of line while looking for the location to nest",
                NEST_INSTRUCTION, self.get_recipe,
                self.basic_header_and_branch + "nest foo url ")

    def test_rejects_text_at_end_of_nest_line(self):
        self.assertInstructionParseError(3, 20,
                "Expecting the end of the line, got 'baz'",
                NEST_INSTRUCTION, self.get_recipe,
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

    def test_rejects_non_unique_ids(self):
        self.assertParseError(4, 7, "'foo' was already used to identify "
                "a branch.", self.get_recipe,
                self.basic_header_and_branch + "merge foo url\n"
                + "merge foo other-url\n")

    def test_rejects_run_with_no_instruction(self):
        self.assertInstructionParseError(3, 4,
                "End of line while looking for the command",
                RUN_INSTRUCTION, self.get_recipe,
                self.basic_header_and_branch + "run\n")

    def test_builds_simplest_recipe(self):
        base_branch = self.get_recipe(self.basic_header_and_branch)
        self.check_base_recipe_branch(base_branch, "http://foo.org/")

    def test_skips_comments(self):
        base_branch = self.get_recipe(self.basic_header + "# comment\n"
                + "http://foo.org/\n")
        self.check_base_recipe_branch(base_branch, "http://foo.org/")

    def test_builds_recipe_with_merge(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "merge bar http://bar.org")
        self.check_base_recipe_branch(base_branch, "http://foo.org/",
                num_child_branches=1)
        child_branch, location = base_branch.child_branches[0].as_tuple()
        self.assertEqual(None, location)
        self.check_recipe_branch(child_branch, "bar", "http://bar.org")

    def test_builds_recipe_with_nest_part(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest-part bar http://bar.org some/path")
        self.check_base_recipe_branch(base_branch, "http://foo.org/",
                num_child_branches=1)
        instruction = base_branch.child_branches[0]
        self.assertEqual(None, instruction.nest_path)
        self.check_recipe_branch(
            instruction.recipe_branch, "bar", "http://bar.org")
        self.assertEqual("some/path", instruction.subpath)
        self.assertEqual(None, instruction.target_subdir)

    def test_builds_recipe_with_nest_part_subdir(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest-part bar http://bar.org some/path target-subdir")
        self.check_base_recipe_branch(base_branch, "http://foo.org/",
                num_child_branches=1)
        instruction = base_branch.child_branches[0]
        self.assertEqual(None, instruction.nest_path)
        self.check_recipe_branch(
            instruction.recipe_branch, "bar", "http://bar.org")
        self.assertEqual("some/path", instruction.subpath)
        self.assertEqual("target-subdir", instruction.target_subdir)

    def test_builds_recipe_with_nest_part_subdir_and_revspec(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest-part bar http://bar.org some/path target-subdir 1234")
        self.check_base_recipe_branch(base_branch, "http://foo.org/",
                num_child_branches=1)
        instruction = base_branch.child_branches[0]
        self.assertEqual(None, instruction.nest_path)
        self.check_recipe_branch(
            instruction.recipe_branch, "bar", "http://bar.org", "1234")
        self.assertEqual("some/path", instruction.subpath)
        self.assertEqual("target-subdir", instruction.target_subdir)

    def test_builds_recipe_with_nest(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest bar http://bar.org baz")
        self.check_base_recipe_branch(base_branch, "http://foo.org/",
                num_child_branches=1)
        child_branch, location = base_branch.child_branches[0].as_tuple()
        self.assertEqual("baz", location)
        self.check_recipe_branch(child_branch, "bar", "http://bar.org")

    def test_builds_recipe_with_nest_then_merge(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest bar http://bar.org baz\nmerge zam lp:zam")
        self.check_base_recipe_branch(base_branch, "http://foo.org/",
                num_child_branches=2)
        child_branch, location = base_branch.child_branches[0].as_tuple()
        self.assertEqual("baz", location)
        self.check_recipe_branch(child_branch, "bar", "http://bar.org")
        child_branch, location = base_branch.child_branches[1].as_tuple()
        self.assertEqual(None, location)
        self.check_recipe_branch(child_branch, "zam", "lp:zam")

    def test_builds_recipe_with_merge_then_nest(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "merge zam lp:zam\nnest bar http://bar.org baz")
        self.check_base_recipe_branch(base_branch, "http://foo.org/",
                num_child_branches=2)
        child_branch, location = base_branch.child_branches[0].as_tuple()
        self.assertEqual(None, location)
        self.check_recipe_branch(child_branch, "zam", "lp:zam")
        child_branch, location = base_branch.child_branches[1].as_tuple()
        self.assertEqual("baz", location)
        self.check_recipe_branch(child_branch, "bar", "http://bar.org")

    def test_builds_a_merge_in_to_a_nest(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest bar http://bar.org baz\n  merge zam lp:zam")
        self.check_base_recipe_branch(base_branch, "http://foo.org/",
                num_child_branches=1)
        child_branch, location = base_branch.child_branches[0].as_tuple()
        self.assertEqual("baz", location)
        self.check_recipe_branch(child_branch, "bar", "http://bar.org",
                num_child_branches=1)
        child_branch, location = child_branch.child_branches[0].as_tuple()
        self.assertEqual(None, location)
        self.check_recipe_branch(child_branch, "zam", "lp:zam")

    def tests_builds_nest_into_a_nest(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest bar http://bar.org baz\n  nest zam lp:zam zoo")
        self.check_base_recipe_branch(base_branch, "http://foo.org/",
                num_child_branches=1)
        child_branch, location = base_branch.child_branches[0].as_tuple()
        self.assertEqual("baz", location)
        self.check_recipe_branch(child_branch, "bar", "http://bar.org",
                num_child_branches=1)
        child_branch, location = child_branch.child_branches[0].as_tuple()
        self.assertEqual("zoo", location)
        self.check_recipe_branch(child_branch, "zam", "lp:zam")

    def tests_builds_recipe_with_revspecs(self):
        base_branch = self.get_recipe(self.basic_header
                + "http://foo.org/ revid:a\n"
                + "nest bar http://bar.org baz tag:b\n"
                + "merge zam lp:zam 2")
        self.check_base_recipe_branch(base_branch, "http://foo.org/",
                num_child_branches=2, revspec="revid:a")
        instruction = base_branch.child_branches[0]
        child_branch = instruction.recipe_branch
        location = instruction.nest_path
        self.assertEqual("baz", location)
        self.check_recipe_branch(child_branch, "bar", "http://bar.org",
                revspec="tag:b")
        child_branch, location = base_branch.child_branches[1].as_tuple()
        self.assertEqual(None, location)
        self.check_recipe_branch(child_branch, "zam", "lp:zam", revspec="2")

    def test_builds_recipe_with_commands(self):
        base_branch = self.get_recipe(self.basic_header
                + "http://foo.org/\n"
                + "run touch test \n")
        self.check_base_recipe_branch(base_branch, "http://foo.org/",
                num_child_branches=1)
        child_branch, command = base_branch.child_branches[0].as_tuple()
        self.assertEqual(None, child_branch)
        self.assertEqual("touch test", command)

    def test_accepts_blank_line_during_nest(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest foo http://bar.org bar\n  merge baz baz.org\n\n"
                "  merge zap zap.org\n")
        self.check_base_recipe_branch(base_branch, self.basic_branch,
                num_child_branches=1)
        nested_branch, location = base_branch.child_branches[0].as_tuple()
        self.assertEqual("bar", location)
        self.check_recipe_branch(nested_branch, "foo", "http://bar.org",
                num_child_branches=2)
        child_branch, location = nested_branch.child_branches[0].as_tuple()
        self.assertEqual(None, location)
        self.check_recipe_branch(child_branch, "baz", "baz.org")
        child_branch, location = nested_branch.child_branches[1].as_tuple()
        self.assertEqual(None, location)
        self.check_recipe_branch(child_branch, "zap", "zap.org")

    def test_accepts_blank_line_at_start_of_nest(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest foo http://bar.org bar\n\n  merge baz baz.org\n")
        self.check_base_recipe_branch(base_branch, self.basic_branch,
                num_child_branches=1)
        nested_branch, location = base_branch.child_branches[0].as_tuple()
        self.assertEqual("bar", location)
        self.check_recipe_branch(nested_branch, "foo", "http://bar.org",
                num_child_branches=1)
        child_branch, location = nested_branch.child_branches[0].as_tuple()
        self.assertEqual(None, location)
        self.check_recipe_branch(child_branch, "baz", "baz.org")

    def test_accepts_blank_line_as_only_thing_in_nest(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest foo http://bar.org bar\n\nmerge baz baz.org\n")
        self.check_base_recipe_branch(base_branch, self.basic_branch,
                num_child_branches=2)
        nested_branch, location = base_branch.child_branches[0].as_tuple()
        self.assertEqual("bar", location)
        self.check_recipe_branch(nested_branch, "foo", "http://bar.org")
        child_branch, location = base_branch.child_branches[1].as_tuple()
        self.assertEqual(None, location)
        self.check_recipe_branch(child_branch, "baz", "baz.org")

    def test_accepts_comment_line_with_any_number_of_spaces(self):
        base_branch = self.get_recipe(self.basic_header_and_branch
                + "nest foo http://bar.org bar\n   #foo\nmerge baz baz.org\n")
        self.check_base_recipe_branch(base_branch, self.basic_branch,
                num_child_branches=2)
        nested_branch, location = base_branch.child_branches[0].as_tuple()
        self.assertEqual("bar", location)
        self.check_recipe_branch(nested_branch, "foo", "http://bar.org")
        child_branch, location = base_branch.child_branches[1].as_tuple()
        self.assertEqual(None, location)
        self.check_recipe_branch(child_branch, "baz", "baz.org")

    def test_old_format_rejects_run(self):
        header = ("# bzr-builder format 0.1 deb-version "
                + self.deb_version +"\n")
        self.assertParseError(3, 1, "Expecting 'merge' or 'nest', got 'run'"
                , self.get_recipe, header + "http://foo.org/\n"
                + "run touch test \n")

    def test_old_format_rejects_nest_part(self):
        header = ("# bzr-builder format 0.2 deb-version "
                + self.deb_version +"\n")
        self.assertParseError(3, 1, "Expecting 'merge', 'nest' or 'run', "
                "got 'nest-part'" , self.get_recipe,
                header + "http://foo.org/\nnest-part packaging foo test \n")

    def test_error_on_forbidden_instructions(self):
        exc = self.assertParseError(3, 1, "The 'run' instruction is "
                "forbidden", self.get_recipe, self.basic_header_and_branch
                + "run touch test\n",
                permitted_instructions=[SAFE_INSTRUCTIONS])
        self.assertTrue(isinstance(exc, ForbiddenInstructionError))
        self.assertEqual("run", exc.instruction_name)

    def test_error_on_duplicate_path(self):
        exc = self.assertInstructionParseError(3, 15,
                "The path '.' is a duplicate of the one used on line 1.",
                NEST_INSTRUCTION, self.get_recipe,
                self.basic_header_and_branch + "nest nest url .\n")

    def test_error_on_duplicate_path_with_another_nest(self):
        exc = self.assertInstructionParseError(4, 16,
                "The path 'foo' is a duplicate of the one used on line 3.",
                NEST_INSTRUCTION, self.get_recipe,
                self.basic_header_and_branch + "nest nest url foo\n"
                + "nest nest2 url foo\n")

    def test_duplicate_path_check_uses_normpath(self):
        exc = self.assertInstructionParseError(3, 15,
                "The path 'foo/..' is a duplicate of the one used on line 1.",
                NEST_INSTRUCTION, self.get_recipe,
                self.basic_header_and_branch + "nest nest url foo/..\n")

    def test_error_absolute_path(self):
        exc = self.assertInstructionParseError(3, 15,
                "Absolute paths are not allowed: /etc/passwd",
                NEST_INSTRUCTION, self.get_recipe,
                self.basic_header_and_branch + "nest nest url /etc/passwd\n")

    def test_error_simple_parent_dir(self):
        exc = self.assertInstructionParseError(3, 15,
                "Paths outside the current directory are not allowed: ../foo",
                NEST_INSTRUCTION, self.get_recipe,
                self.basic_header_and_branch + "nest nest url ../foo\n")

    def test_error_complex_parent_dir(self):
        exc = self.assertInstructionParseError(3, 15,
                "Paths outside the current directory are not allowed:"
                " ./foo/../..", NEST_INSTRUCTION, self.get_recipe,
                self.basic_header_and_branch + "nest nest url ./foo/../..\n")


class BuildTreeTests(TestCaseWithTransport):

    if not getattr(TestCaseWithTransport, "assertPathExists", None):
        # Compatibility with bzr < 2.4
        def assertPathExists(self, path):
            self.failUnlessExists(path)

    def test_ensure_basedir(self):
        to_transport = transport.get_transport("a")
        ensure_basedir(to_transport)
        self.assertPathExists("a")
        ensure_basedir(to_transport)
        self.assertPathExists("a")
        e = self.assertRaises(errors.BzrCommandError, ensure_basedir,
                transport.get_transport("b/c"))
        self.assertTrue('Parent of "' in str(e))
        self.assertTrue('" does not exist.' in str(e))

    def test_build_tree_single_branch(self):
        source = self.make_branch_and_tree("source")
        revid = source.commit("one")
        base_branch = BaseRecipeBranch("source", "1", 0.2)
        build_tree(base_branch, "target")
        self.assertPathExists("target")
        tree = workingtree.WorkingTree.open("target")
        self.assertEqual(revid, tree.last_revision())
        self.assertEqual(revid, base_branch.revid)

    def test_build_tree_single_branch_dir_not_branch(self):
        source = self.make_branch_and_tree("source")
        revid = source.commit("one")
        # We just create the target as a directory
        os.mkdir("target")
        base_branch = BaseRecipeBranch("source", "1", 0.2)
        build_tree(base_branch, "target")
        self.assertPathExists("target")
        tree = workingtree.WorkingTree.open("target")
        self.assertEqual(revid, tree.last_revision())
        self.assertEqual(revid, base_branch.revid)

    def test_build_tree_single_branch_existing_branch(self):
        source = self.make_branch_and_tree("source")
        revid = source.commit("one")
        self.make_branch_and_tree("target")
        base_branch = BaseRecipeBranch("source", "1", 0.2)
        build_tree(base_branch, "target")
        self.assertPathExists("target")
        tree = workingtree.WorkingTree.open("target")
        self.assertEqual(revid, tree.last_revision())
        self.assertEqual(revid, base_branch.revid)

    def make_source_branch(self, relpath):
        """Make a branch with one file and one commit."""
        source1 = self.make_branch_and_tree(relpath)
        self.build_tree([relpath + "/a"])
        source1.add(["a"])
        source1.commit("one")
        return source1

    def test_build_tree_nested(self):
        source1_rev_id = self.make_source_branch("source1").last_revision()
        source2_rev_id = self.make_source_branch("source2").last_revision()
        base_branch = BaseRecipeBranch("source1", "1", 0.2)
        nested_branch = RecipeBranch("nested", "source2")
        base_branch.nest_branch("sub", nested_branch)
        build_tree(base_branch, "target")
        self.assertPathExists("target")
        tree = workingtree.WorkingTree.open("target")
        self.assertEqual([source1_rev_id], tree.get_parent_ids())
        tree = workingtree.WorkingTree.open("target/sub")
        self.assertEqual([source2_rev_id], tree.get_parent_ids())
        self.assertEqual(source1_rev_id, base_branch.revid)
        self.assertEqual(source2_rev_id, nested_branch.revid)

    def test_build_tree_merged(self):
        source1 = self.make_source_branch("source1")
        source1_rev_id = source1.last_revision()
        source2 = source1.controldir.sprout("source2").open_workingtree()
        self.build_tree_contents([("source2/a", "other change")])
        source2_rev_id = source2.commit("one")
        base_branch = BaseRecipeBranch("source1", "1", 0.2)
        merged_branch = RecipeBranch("merged", "source2")
        base_branch.merge_branch(merged_branch)
        build_tree(base_branch, "target")
        self.assertPathExists("target")
        tree = workingtree.WorkingTree.open("target")
        last_revid = tree.last_revision()
        last_revtree = tree.branch.repository.revision_tree(last_revid)
        self.assertEqual([source1_rev_id, source2_rev_id],
                last_revtree.get_parent_ids())
        self.check_file_contents("target/a", "other change")
        self.assertEqual(source1_rev_id, base_branch.revid)
        self.assertEqual(source2_rev_id, merged_branch.revid)

    def test_build_tree_merge_unrelated(self):
        """Make a branch with one file and one commit."""
        source1 = self.make_branch_and_tree("source1")
        self.build_tree_contents([("source1/a", "file a")])
        source1.add(["a"])
        source1_rev_id = source1.commit("one")

        source2 = self.make_branch_and_tree("source2")
        self.build_tree_contents([("source2/b", "file b")])
        source2.add(["b"])
        source2_rev_id = source2.commit("one")

        base_branch = BaseRecipeBranch("source1", "1", 0.2)
        merged_branch = RecipeBranch("merged", "source2")
        base_branch.merge_branch(merged_branch)
        build_tree(base_branch, "target")
        self.assertPathExists("target")
        tree = workingtree.WorkingTree.open("target")
        last_revid = tree.last_revision()
        last_revtree = tree.branch.repository.revision_tree(last_revid)
        self.assertEqual([source1_rev_id, source2_rev_id],
                last_revtree.get_parent_ids())
        self.check_file_contents("target/a", "file a")
        self.check_file_contents("target/b", "file b")
        self.assertEqual(source1_rev_id, base_branch.revid)
        self.assertEqual(source2_rev_id, merged_branch.revid)

    def test_build_tree_implicit_dir(self):
        # Branches nested into non-existant directories trigger creation of
        # those directories.
        source1 = self.make_source_branch("source1")
        source2 = self.make_source_branch("source2")
        source3 = self.make_source_branch("source3")
        self.build_tree_contents([
            ("source2/file", "new file"),
            ("source3/yetanotherfile", "rugby")])
        source2.add(["file"])
        source2.commit("two")
        source3.add(["yetanotherfile"])
        source3.commit("three")
        base_branch = BaseRecipeBranch("source1", "1", 0.4)
        merged_branch_2 = RecipeBranch("merged", "source2")
        # Merge source2 into path implicit/b
        base_branch.nest_part_branch(merged_branch_2, ".",
            target_subdir="implicit/b")
        # Merge source3 into path implicit/moreimplicit/c
        merged_branch_3 = RecipeBranch("merged", "source3")
        base_branch.nest_part_branch(merged_branch_3, ".",
            target_subdir="moreimplicit/another/c")
        build_tree(base_branch, "target")
        self.check_file_contents("target/implicit/b/file", "new file")
        self.check_file_contents("target/moreimplicit/another/c/yetanotherfile",
            "rugby")

    def test_build_tree_nest_part(self):
        """A recipe can specify a merge of just part of an unrelated tree."""
        source1 = self.make_source_branch("source1")
        source2 = self.make_source_branch("source2")
        source1.lock_read()
        self.addCleanup(source1.unlock)
        source1_rev_id = source1.last_revision()
        # Add 'b' to source2.
        self.build_tree_contents([
            ("source2/b", "new file"), ("source2/not-b", "other file")])
        source2.add(["b", "not-b"])
        source2_rev_id = source2.commit("two")
        base_branch = BaseRecipeBranch("source1", "1", 0.2)
        merged_branch = RecipeBranch("merged", "source2")
        # Merge just 'b' from source2; 'a' is untouched.
        base_branch.nest_part_branch(merged_branch, "b")
        build_tree(base_branch, "target")
        self.check_file_contents("target/a", source1.get_file_text('a'))
        self.check_file_contents("target/b", "new file")
        self.assertNotInWorkingTree("not-b", "target")
        self.assertEqual(source1_rev_id, base_branch.revid)
        self.assertEqual(source2_rev_id, merged_branch.revid)

    def test_build_tree_nest_part_explicit_target(self):
        """A recipe can specify a merge of just part of an unrelated tree into
        a specific subdirectory of the target tree.
        """
        source1 = self.make_branch_and_tree("source1")
        self.build_tree(["source1/dir/"])
        source1.add(["dir"])
        source1.commit("one")
        source2 = self.make_source_branch("source2")
        source1.lock_read()
        self.addCleanup(source1.unlock)
        source1_rev_id = source1.last_revision()
        # Add 'b' to source2.
        self.build_tree_contents([
            ("source2/b", "new file"), ("source2/not-b", "other file")])
        source2.add(["b", "not-b"])
        source2_rev_id = source2.commit("two")
        base_branch = BaseRecipeBranch("source1", "1", 0.2)
        merged_branch = RecipeBranch("merged", "source2")
        # Merge just 'b' from source2; 'a' is untouched.
        base_branch.nest_part_branch(merged_branch, "b", "dir/b")
        build_tree(base_branch, "target")
        self.check_file_contents("target/dir/b", "new file")
        self.assertNotInWorkingTree("dir/not-b", "target")
        self.assertEqual(source1_rev_id, base_branch.revid)
        self.assertEqual(source2_rev_id, merged_branch.revid)

    def test_build_tree_merge_twice(self):
        source1 = self.make_source_branch("source1")
        source1_rev_id = source1.last_revision()
        source2 = source1.controldir.sprout("source2").open_workingtree()
        self.build_tree_contents([("source2/a", "other change")])
        source2_rev_id = source2.commit("one")
        source3 = source2.controldir.sprout("source3").open_workingtree()
        self.build_tree_contents([("source3/a", "third change")])
        source3_rev_id = source3.commit("one")
        base_branch = BaseRecipeBranch("source1", "1", 0.2)
        merged_branch1 = RecipeBranch("merged", "source2")
        base_branch.merge_branch(merged_branch1)
        merged_branch2 = RecipeBranch("merged2", "source3")
        base_branch.merge_branch(merged_branch2)
        build_tree(base_branch, "target")
        self.assertPathExists("target")
        tree = workingtree.WorkingTree.open("target")
        last_revid = tree.last_revision()
        previous_revid = tree.branch.repository.get_revision(tree.branch.last_revision()).parent_ids[0]
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
        source1 = self.make_source_branch("source1")
        source2 = source1.controldir.sprout("source2").open_workingtree()
        self.build_tree_contents([("source2/a", "other change\n")])
        source2_rev_id = source2.commit("one")
        self.build_tree_contents([("source1/a", "trunk change\n")])
        source1_rev_id = source1.commit("two")
        base_branch = BaseRecipeBranch("source1", "1", 0.2)
        merged_branch = RecipeBranch("merged", "source2")
        base_branch.merge_branch(merged_branch)
        self.assertRaises(errors.BzrCommandError, build_tree,
                base_branch, "target")
        self.assertPathExists("target")
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
        source1 = self.make_source_branch("source1")
        source1_rev_id = source1.last_revision()
        source2 = source1.controldir.sprout("source2").open_workingtree()
        self.build_tree_contents([("source2/a", "other change\n")])
        source2_rev_id = source2.commit("one")
        self.build_tree_contents([("source2/a", "unwanted change\n")])
        source2.commit("one")
        self.build_tree_contents([("source1/a", "unwanted trunk change\n")])
        source1.commit("two")
        base_branch = BaseRecipeBranch("source1", "1", 0.2, revspec="1")
        merged_branch = RecipeBranch("merged", "source2", revspec="2")
        base_branch.merge_branch(merged_branch)
        build_tree(base_branch, "target")
        self.assertPathExists("target")
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
        tree_to.controldir.destroy_workingtree()
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

    def test_build_tree_runs_commands(self):
        source = self.make_branch_and_tree("source")
        revid = source.commit("one")
        base_branch = BaseRecipeBranch("source", "1", 0.2)
        base_branch.run_command("touch test")
        build_tree(base_branch, "target")
        self.assertPathExists("target")
        self.assertPathExists("target/test")
        tree = workingtree.WorkingTree.open("target")
        self.assertEqual(revid, tree.last_revision())
        self.assertEqual(revid, base_branch.revid)

    def test_error_on_merge_revspec(self):
        # See bug 416950
        source = self.make_branch_and_tree("source")
        revid = source.commit("one")
        base_branch = BaseRecipeBranch("source", "1", 0.2)
        merged_branch = RecipeBranch("merged", "source", revspec="debian")
        base_branch.merge_branch(merged_branch)
        e = self.assertRaises(errors.InvalidRevisionSpec,
                build_tree, base_branch, "target")
        self.assertTrue(str(e).startswith("Requested revision: 'debian' "
                    "does not exist in branch: "))
        self.assertTrue(str(e).endswith(". Did you not mean to specify a "
                    "revspec at the end of the merge line?"))


class StringifyTests(TestCaseInTempDir):

    def test_missing_debversion(self):
        base_branch = BaseRecipeBranch("base_url", None, 0.1)
        base_branch.revid = "base_revid"
        manifest = str(base_branch)
        self.assertEqual("# bzr-builder format 0.1\n"
                "base_url revid:base_revid\n", manifest)

    def test_simple_manifest(self):
        base_branch = BaseRecipeBranch("base_url", "1", 0.1)
        base_branch.revid = "base_revid"
        manifest = str(base_branch)
        self.assertEqual("# bzr-builder format 0.1 deb-version 1\n"
                "base_url revid:base_revid\n", manifest)

    def test_complex_manifest(self):
        base_branch = BaseRecipeBranch("base_url", "2", 0.2)
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
        manifest = str(base_branch)
        self.assertEqual("# bzr-builder format 0.2 deb-version 2\n"
                "base_url revid:base_revid\n"
                "nest nested1 nested1_url nested revid:nested1_revid\n"
                "  nest nested2 nested2_url nested2 revid:nested2_revid\n"
                "merge merged merged_url revid:merged_revid\n", manifest)

    def test_manifest_with_command(self):
        base_branch = BaseRecipeBranch("base_url", "1", 0.2)
        base_branch.revid = "base_revid"
        base_branch.run_command("touch test")
        manifest = str(base_branch)
        self.assertEqual("# bzr-builder format 0.2 deb-version 1\n"
                "base_url revid:base_revid\n"
                "run touch test\n", manifest)

    def test_recipe_with_no_revspec(self):
        base_branch = BaseRecipeBranch("base_url", "1", 0.1)
        manifest = str(base_branch)
        self.assertEqual("# bzr-builder format 0.1 deb-version 1\n"
                "base_url\n", manifest)

    def test_recipe_with_tag_revspec(self):
        base_branch = BaseRecipeBranch("base_url", "1", 0.1,
                revspec="tag:foo")
        manifest = str(base_branch)
        self.assertEqual("# bzr-builder format 0.1 deb-version 1\n"
                "base_url tag:foo\n", manifest)

    def test_recipe_with_child(self):
        base_branch = BaseRecipeBranch("base_url", "2", 0.2)
        nested_branch1 = RecipeBranch("nested1", "nested1_url",
                revspec="tag:foo")
        base_branch.nest_branch("nested", nested_branch1)
        nested_branch2 = RecipeBranch("nested2", "nested2_url")
        nested_branch1.nest_branch("nested2", nested_branch2)
        merged_branch = RecipeBranch("merged", "merged_url")
        base_branch.merge_branch(merged_branch)
        manifest = str(base_branch)
        self.assertEqual("# bzr-builder format 0.2 deb-version 2\n"
                "base_url\n"
                "nest nested1 nested1_url nested tag:foo\n"
                "  nest nested2 nested2_url nested2\n"
                "merge merged merged_url\n", manifest)

    def test_get_recipe_text(self):
        base_branch = BaseRecipeBranch("base_url", "1", 0.1)
        base_branch.revid = "base_revid"
        manifest = base_branch.get_recipe_text()
        self.assertEqual("# bzr-builder format 0.1 deb-version 1\n"
                "base_url revid:base_revid\n", manifest)

    def test_get_recipe_doesnt_raise_on_invalid_recipe(self):
        base_branch = BaseRecipeBranch("base_url", "1", 0.1)
        base_branch.revid = "base_revid"
        nested_branch1 = RecipeBranch("nested1", "nested1_url",
                revspec="tag:foo")
        base_branch.nest_branch(".", nested_branch1)
        manifest = base_branch.get_recipe_text()
        self.assertEqual("# bzr-builder format 0.1 deb-version 1\n"
                "base_url revid:base_revid\n"
                "nest nested1 nested1_url . tag:foo\n", manifest)

    def test_get_recipe_text_validate_True(self):
        base_branch = BaseRecipeBranch("base_url", "1", 0.1)
        base_branch.revid = "base_revid"
        nested_branch1 = RecipeBranch("nested1", "nested1_url",
                revspec="tag:foo")
        base_branch.nest_branch(".", nested_branch1)
        self.assertRaises(InstructionParseError,
            base_branch.get_recipe_text, validate=True)

    def test_str_validates(self):
        base_branch = BaseRecipeBranch("base_url", "1", 0.1)
        base_branch.revid = "base_revid"
        nested_branch1 = RecipeBranch("nested1", "nested1_url",
                revspec="tag:foo")
        base_branch.nest_branch(".", nested_branch1)
        self.assertRaises(InstructionParseError, str, base_branch)

    def test_with_nest_part(self):
        base_branch = BaseRecipeBranch("base_url", "1", 0.1)
        base_branch.revid = "base_revid"
        nested_branch1 = RecipeBranch("nested1", "nested1_url",
                revspec="tag:foo")
        base_branch.nest_part_branch(nested_branch1, "foo", "bar")
        manifest = base_branch.get_recipe_text()
        self.assertEqual("# bzr-builder format 0.1 deb-version 1\n"
                "base_url revid:base_revid\n"
                "nest-part nested1 nested1_url foo bar tag:foo\n",
                manifest)

    def test_with_nest_part_with_no_target_dir(self):
        base_branch = BaseRecipeBranch("base_url", "1", 0.1)
        base_branch.revid = "base_revid"
        nested_branch1 = RecipeBranch("nested1", "nested1_url",
                revspec="tag:foo")
        base_branch.nest_part_branch(nested_branch1, "foo", None)
        manifest = base_branch.get_recipe_text()
        self.assertEqual("# bzr-builder format 0.1 deb-version 1\n"
                "base_url revid:base_revid\n"
                "nest-part nested1 nested1_url foo foo tag:foo\n",
                manifest)

    def test_with_nest_part_with_no_target_dir_no_revspec(self):
        base_branch = BaseRecipeBranch("base_url", "1", 0.1)
        base_branch.revid = "base_revid"
        nested_branch1 = RecipeBranch("nested1", "nested1_url")
        base_branch.nest_part_branch(nested_branch1, "foo", None)
        manifest = base_branch.get_recipe_text()
        self.assertEqual("# bzr-builder format 0.1 deb-version 1\n"
                "base_url revid:base_revid\n"
                "nest-part nested1 nested1_url foo\n",
                manifest)


class RecipeBranchTests(TestCaseWithTransport):

    def test_base_recipe_branch(self):
        base_branch = BaseRecipeBranch("base_url", "1", 0.2, revspec="2")
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
        branch1 = BaseRecipeBranch("base_url", "1", 0.2, revspec="2")
        branch2 = BaseRecipeBranch("base_url", "1", 0.2, revspec="3")
        self.assertFalse(branch1.different_shape_to(branch2))
        branch2 = BaseRecipeBranch("base", "1", 0.2, revspec="2")
        self.assertTrue(branch1.different_shape_to(branch2))
        branch2 = BaseRecipeBranch("base_url", "2", 0.2, revspec="2")
        self.assertFalse(branch1.different_shape_to(branch2))
        rbranch1 = RecipeBranch("name", "other_url")
        rbranch2 = RecipeBranch("name2", "other_url")
        self.assertTrue(rbranch1.different_shape_to(rbranch2))
        rbranch2 = RecipeBranch("name", "other_url2")
        self.assertTrue(rbranch1.different_shape_to(rbranch2))

    def test_list_branch_names(self):
        base_branch = BaseRecipeBranch("base_url", "1", 0.2)
        base_branch.merge_branch(RecipeBranch("merged", "merged_url"))
        nested_branch = RecipeBranch("nested", "nested_url")
        nested_branch.merge_branch(
            RecipeBranch("merged_into_nested", "another_url"))
        base_branch.nest_branch("subdir", nested_branch)
        base_branch.merge_branch(
            RecipeBranch("another_nested", "yet_another_url"))
        base_branch.run_command("a command")
        self.assertEqual(
            ["merged", "nested", "merged_into_nested", "another_nested"],
            base_branch.list_branch_names())

    def test_iter_all_branches(self):
        base_branch = BaseRecipeBranch("base_url", "1", 0.2)
        merged_branch = RecipeBranch("merged", "merged_url")
        base_branch.merge_branch(merged_branch)
        nested_branch = RecipeBranch("nested", "nested_url")
        merge_into_nested_branch = RecipeBranch("merged_into_nested", "another_url")
        nested_branch.merge_branch(merge_into_nested_branch)
        base_branch.nest_branch("subdir", nested_branch)
        another_nested_branch = RecipeBranch("another_nested", "yet_another_url")
        base_branch.merge_branch(another_nested_branch)
        base_branch.run_command("a command")
        self.assertEqual([
            base_branch, merged_branch, nested_branch, merge_into_nested_branch,
            another_nested_branch],
            list(base_branch.iter_all_branches()))

    def test_iter_all_instructions(self):
        base_branch = BaseRecipeBranch("base_url", "1", 0.2)
        nested_branch = RecipeBranch("nested", "nested_url")
        merge_into_nested_branch = RecipeBranch("merged_into_nested", "another_url")
        nested_branch.merge_branch(merge_into_nested_branch)
        merge_into_nested = nested_branch.child_branches[-1]
        base_branch.run_command("a command")
        cmd = base_branch.child_branches[-1]
        base_branch.nest_branch("subdir", nested_branch)
        nest = base_branch.child_branches[-1]
        self.assertEqual([
            cmd, nest, merge_into_nested],
            list(base_branch.iter_all_instructions()))
