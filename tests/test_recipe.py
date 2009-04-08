
from bzrlib.tests import TestCaseInTempDir
from bzrlib.plugins.builder.recipe import Recipe, RecipeParseError

class RecipeParserTests(TestCaseInTempDir):

    basic_header = "# bzr-builder format 0.1 deb-version 0.1-{revision}\n"

    def get_recipe(self, recipe_text):
        return Recipe(recipe_text)

    def assertParseError(self, line, char, problem, callable, *args,
            **kwargs):
        exc = self.assertRaises(RecipeParseError, callable, *args, **kwargs)
        self.assertEqual(line, exc.line)
        self.assertEqual(char, exc.char)
        self.assertEqual(problem, exc.problem)
        self.assertEqual("recipe", exc.filename)

    def test_parses_most_basic(self):
        self.get_recipe(self.basic_header +
                "bzr+ssh://src.upstream.org/trunk")

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
