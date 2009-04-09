
from bzrlib.tests import TestCaseInTempDir
from bzrlib.plugins.builder.recipe import Recipe, RecipeParseError

class RecipeParserTests(TestCaseInTempDir):

    basic_header = "# bzr-builder format 0.1 deb-version 0.1-{revision}\n"
    basic_header_and_branch = basic_header + "http://foo.org/\n"

    def get_recipe(self, recipe_text):
        return Recipe(recipe_text)

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
        recipe = self.get_recipe(self.basic_header_and_branch)
        self.assertEqual("", recipe.base_branch.name)
        self.assertEqual("http://foo.org/", recipe.base_branch.url)
        self.assertEqual(0, len(recipe.base_branch.child_branches))

    def test_builds_recipe_with_merge(self):
        recipe = self.get_recipe(self.basic_header_and_branch
                + "merge bar http://bar.org")
        self.assertEqual("", recipe.base_branch.name)
        self.assertEqual("http://foo.org/", recipe.base_branch.url)
        self.assertEqual(1, len(recipe.base_branch.child_branches))
        child_branch, location = recipe.base_branch.child_branches[0]
        self.assertEqual(None, location)
        self.assertEqual("bar", child_branch.name)
        self.assertEqual("http://bar.org", child_branch.url)
        self.assertEqual(0, len(child_branch.child_branches))

    def test_builds_recipe_with_nest(self):
        recipe = self.get_recipe(self.basic_header_and_branch
                + "nest bar http://bar.org baz")
        self.assertEqual("", recipe.base_branch.name)
        self.assertEqual("http://foo.org/", recipe.base_branch.url)
        self.assertEqual(1, len(recipe.base_branch.child_branches))
        child_branch, location = recipe.base_branch.child_branches[0]
        self.assertEqual("baz", location)
        self.assertEqual("bar", child_branch.name)
        self.assertEqual("http://bar.org", child_branch.url)
        self.assertEqual(0, len(child_branch.child_branches))

    def test_builds_recipe_with_nest_then_merge(self):
        recipe = self.get_recipe(self.basic_header_and_branch
                + "nest bar http://bar.org baz\nmerge zam lp:zam")
        self.assertEqual("", recipe.base_branch.name)
        self.assertEqual("http://foo.org/", recipe.base_branch.url)
        self.assertEqual(2, len(recipe.base_branch.child_branches))
        child_branch, location = recipe.base_branch.child_branches[0]
        self.assertEqual("baz", location)
        self.assertEqual("bar", child_branch.name)
        self.assertEqual("http://bar.org", child_branch.url)
        self.assertEqual(0, len(child_branch.child_branches))
        child_branch, location = recipe.base_branch.child_branches[1]
        self.assertEqual(None, location)
        self.assertEqual("zam", child_branch.name)
        self.assertEqual("lp:zam", child_branch.url)
        self.assertEqual(0, len(child_branch.child_branches))

    def test_builds_recipe_with_merge_then_nest(self):
        recipe = self.get_recipe(self.basic_header_and_branch
                + "merge zam lp:zam\nnest bar http://bar.org baz")
        self.assertEqual("", recipe.base_branch.name)
        self.assertEqual("http://foo.org/", recipe.base_branch.url)
        self.assertEqual(2, len(recipe.base_branch.child_branches))
        child_branch, location = recipe.base_branch.child_branches[0]
        self.assertEqual(None, location)
        self.assertEqual("zam", child_branch.name)
        self.assertEqual("lp:zam", child_branch.url)
        self.assertEqual(0, len(child_branch.child_branches))
        child_branch, location = recipe.base_branch.child_branches[1]
        self.assertEqual("baz", location)
        self.assertEqual("bar", child_branch.name)
        self.assertEqual("http://bar.org", child_branch.url)
        self.assertEqual(0, len(child_branch.child_branches))
