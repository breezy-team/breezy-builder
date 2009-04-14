import os

from bzrlib import (
        branch,
        bzrdir,
        errors,
        tag,
        transport,
        workingtree,
        )


def ensure_basedir(to_location):
    to_transport = transport.get_transport(to_location)
    try:
        to_transport.mkdir('.')
    except errors.FileExists:
        pass
    except errors.NoSuchFile:
        raise errors.BzrCommandError('Parent of "%s" does not exist.'
                                     % to_location)
    return to_transport


def pull_or_branch(tree_to, br_to, br_from, to_transport, accelerator_tree,
        possible_transports):
    created_tree_to = False
    created_br_to = False
    if br_to is None:
        # We do a "branch"
        revision_id = br_from.last_revision()
        dir = br_from.bzrdir.sprout(to_transport.base, revision_id,
                                    possible_transports=possible_transports,
                                    accelerator_tree=accelerator_tree,
                                    stacked=True, source_branch=br_from)
        try:
            tree_to = dir.open_workingtree()
        except errors.NoWorkingTree:
            # There's no working tree, so it's probably in a no-trees repo,
            # but the whole point of this is to create trees, so we should
            # forcibly create one.
            tree_to = dir.create_workingtree()
        br_to = tree_to.branch
        created_br_to = True
        tag._merge_tags_if_possible(br_from, br_to)
        created_tree_to = True
    else:
        # We do a "pull"
        if tree_to is not None:
            # FIXME: should these pulls overwrite?
            result = tree_to.pull(br_from,
                    possible_transports=possible_transports)
        else:
            result = br_to.pull(br_from,
                    possible_transports=possible_transports)
            tree_to = br_to.bzrdir.create_workingtree()
            # Ugh, we have to assume that the caller replaces their reference
            # to the branch with the one we return.
            br_to.unlock()
            br_to = tree_to.branch
            br_to.lock_write()
            created_tree_to = True
    if created_tree_to:
        tree_to.lock_write()
    try:
        if created_br_to:
            br_to.lock_write()
        try:
            conflicts = tree_to.conflicts()
            if len(conflicts) > 0:
                # FIXME: better reporting
                raise errors.BzrCommandError("Conflicts... aborting.")
        except:
            if created_br_to:
                br_to.unlock()
            raise
    except:
        if created_tree_to:
            tree_to.unlock()
        raise
    return tree_to, br_to


def build_tree(base_branch, target_path):
    to_transport = ensure_basedir(target_path)
    try:
        tree_to, br_to = bzrdir.BzrDir.open_tree_or_branch(target_path)
    except errors.NotBranchError:
        tree_to = None
        br_to = None
    if tree_to is not None:
        tree_to.lock_write()
    try:
        if br_to is not None:
            br_to.lock_write()
        try:
            from_location = base_branch.url
            accelerator_tree, br_from = bzrdir.BzrDir.open_tree_or_branch(
                                from_location)
            br_from.lock_read()
            try:
                tree_to, br_to = pull_or_branch(tree_to, br_to, br_from,
                        to_transport, accelerator_tree,
                        possible_transports=[to_transport])
            finally:
                br_from.unlock()
        finally:
            # Is this ok if tree_to is created by pull_or_branch
            if br_to is not None:
                br_to.unlock()
    finally:
        if tree_to is not None:
            tree_to.unlock()


class RecipeBranch(object):

    def __init__(self, name, url):
        self.name = name
        self.url = url
        self.child_branches = []

    def merge_branch(self, branch):
        self.child_branches.append((branch, None))

    def nest_branch(self, location, branch):
        assert location not in [b[1] for b in self.child_branches],\
            "%s already has branch nested there" % location
        self.child_branches.append((branch, location))


class RecipeParseError(errors.BzrError):
    _fmt = "Error parsing %(filename)s:%(line)s:%(char)s: %(problem)s."

    def __init__(self, filename, line, char, problem):
        errors.BzrError.__init__(self, filename=filename, line=line, char=char,
                problem=problem)


class _RecipeParser(object):

    whitespace_chars = " \t"
    eol_char = "\n"
    digit_chars = ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9")

    def __init__(self, f, filename=None):
        if getattr(f, "read", None) is not None:
            self.text = f.read()
        else:
            self.text = f
        self.filename = filename
        if filename is None:
            self.filename = "recipe"

    def parse(self):
        self.lines = self.text.split("\n")
        self.index = 0
        self.line_index = 0
        self.current_line = self.lines[self.line_index]
        self.current_indent_level = 0
        self.parse_header()
        last_instruction = None
        active_branches = []
        last_branch = None
        while self.line_index < len(self.lines):
            old_indent_level = self.parse_indent()
            if old_indent_level is not None:
                if (old_indent_level < self.current_indent_level
                    and last_instruction != "nest"):
                    self.throw_parse_error("Not allowed to indent unless "
                            "after a 'nest' line")
                if old_indent_level < self.current_indent_level:
                    active_branches.append(last_branch)
                else:
                    unindent = self.current_indent_level - old_indent_level
                    active_branches = active_branches[:unindent]
            comment = self.parse_comment_line()
            if comment is not None:
                self.new_line()
                continue
            if last_instruction is None:
                url = self.take_to_whitespace("branch to start from")
                last_branch = RecipeBranch("", url)
                active_branches = [last_branch]
                last_instruction = ""
                self.new_line()
            else:
                # FIXME: should parse whitespace before each item, rather
                # than after, so you can get told what is missing if it
                # is not there, rather than just that it was looking for
                # whitespace.
                instruction = self.parse_instruction()
                branch_id = self.parse_branch_id()
                url = self.parse_branch_url()
                if instruction == "nest":
                    self.parse_whitespace()
                    location = self.parse_branch_location()
                last_branch = RecipeBranch(branch_id, url)
                if instruction == "nest":
                    active_branches[-1].nest_branch(location, last_branch)
                else:
                    active_branches[-1].merge_branch(last_branch)
                last_instruction = instruction
                self.new_line()
        if len(active_branches) == 0:
            self.throw_parse_error("Empty recipe")
        return active_branches[0]

    def parse_header(self):
        self.parse_char("#", require_whitespace=False)
        self.parse_word("bzr-builder")
        self.parse_word("format")
        version = self.parse_float()
        self.parse_whitespace()
        self.parse_word("deb-version")
        deb_version = self.take_to_whitespace("a value for 'deb-version'")
        self.new_line()

    def parse_instruction(self):
        instruction = self.peek_to_whitespace()
        if instruction is None:
            self.throw_parse_error("End of line while looking for 'nest' "
                    "or 'merge'")
        if instruction == "nest" or instruction == "merge":
            self.take_chars(len(instruction))
            self.parse_whitespace()
            return instruction
        self.throw_parse_error("Expecting 'nest' or 'merge', got '%s'"
                % instruction)

    def parse_branch_id(self):
        branch_id = self.take_to_whitespace("the branch id")
        self.parse_whitespace()
        return branch_id

    def parse_branch_url(self):
        branch_url = self.take_to_whitespace("the branch url")
        return branch_url

    def parse_branch_location(self):
        # FIXME: Needs a better term
        location = self.take_to_whitespace("the location to nest")
        return location

    def throw_parse_error(self, problem):
        raise RecipeParseError(self.filename, self.line_index + 1,
                self.index + 1, problem)

    def throw_expecting_error(self, expected, actual):
        self.throw_parse_error("Expecting '%s', got '%s'"
                % (expected, actual))

    def throw_eol(self, expected):
        self.throw_parse_error("End of line while looking for '%s'" % expected)

    def new_line(self):
        # Jump over any whitespace
        self.parse_whitespace(require=False)
        remaining = self.peek_to_whitespace()
        if remaining != None:
            self.throw_parse_error("Expecting the end of the line, got '%s'"
                    % remaining)
        self.index = 0
        self.line_index += 1
        if self.line_index >= len(self.lines):
            self.current_line = None
        else:
            self.current_line = self.lines[self.line_index]

    def take_char(self):
        if self.index >= len(self.current_line):
            return None
        self.index += 1
        return self.current_line[self.index-1]

    def take_chars(self, num):
        ret = ""
        for i in range(num):
            char = self.take_char()
            if char is None:
                return None
            ret += char
        return ret

    def peek_char(self, skip=0):
        if self.index + skip >= len(self.current_line):
            return None
        return self.current_line[self.index + skip]

    def parse_char(self, char, require_whitespace=True):
        actual = self.peek_char()
        if actual is None:
            self.throw_eol(char)
        if actual == char:
            self.take_char()
            self.parse_whitespace(require=require_whitespace)
            return char
        self.throw_expecting_error(char, actual)

    def parse_indent(self):
        """Parse the indent from the start of the line."""
        # FIXME: should just peek the whitespace
        new_indent = self.parse_whitespace(require=False)
        # FIXME: These checks should probably come after we check whether
        # any change in indent is legal at this point:
        # "Indents of 3 spaces aren't allowed" -> make it 2 spaces
        # -> "oh, you aren't allowed to indent at that point anyway"
        if "\t" in new_indent:
            self.throw_parse_error("Indents may not be done by tabs")
        if (len(new_indent) % 2 != 0):
            self.throw_parse_error("Indent not a multiple of two spaces")
        new_indent_level = len(new_indent) / 2
        if new_indent_level != self.current_indent_level:
           old_indent_level = self.current_indent_level
           self.current_indent_level = new_indent_level
           if (new_indent_level > old_indent_level
                   and new_indent_level - old_indent_level != 1):
               self.throw_parse_error("Indented by more than two spaces "
                       "at once")
           return old_indent_level
        return None

    def parse_whitespace(self, require=True):
        if require:
            actual = self.peek_char()
            if actual is None:
                self.throw_parse_error("End of line while looking for "
                        "whitespace")
            if actual not in self.whitespace_chars:
                self.throw_parse_error("Expecting whitespace, got '%s'."
                        % actual)
        ret = ""
        actual = self.peek_char()
        while (actual is not None and actual in self.whitespace_chars):
            self.take_char()
            ret += actual
            actual = self.peek_char()
        return ret

    def parse_word(self, expected):
        length = len(expected)
        actual = self.peek_to_whitespace()
        if actual == expected:
            self.take_chars(length)
            self.parse_whitespace()
            return expected
        if actual is None:
            self.throw_eol(expected)
        self.throw_expecting_error(expected, actual)

    def peek_to_whitespace(self):
        ret = ""
        char = self.peek_char()
        if char is None:
            return char
        count = 0
        while char is not None and char not in self.whitespace_chars:
            ret += char
            count += 1
            char = self.peek_char(skip=count)
        return ret

    def take_to_whitespace(self, looking_for):
        text = self.peek_to_whitespace()
        if text is None:
            self.throw_parse_error("End of line while looking for %s"
                    % looking_for)
        self.take_chars(len(text))
        return text

    def parse_float(self):
        ret = self._parse_integer()
        if ret == "":
            self.throw_parse_error("Expecting a float, got '%s'" %
                    self.peek_to_whitespace())
        if self.peek_char(skip=len(ret)) == ".":
            ret2 = self._parse_integer(skip=len(ret)+1)
            if ret2 == "":
                self.throw_parse_error("Expecting a float, got '%s'" %
                    self.peek_to_whitespace())
            ret += "." + ret2
        self.take_chars(len(ret))
        return ret

    def _parse_integer(self, skip=0):
        i = skip
        ret = ""
        while True:
            char = self.peek_char(skip=i)
            if char not in self.digit_chars:
                break
            ret += char
            i = i+1
        return ret

    def parse_integer(self):
        ret = self._parse_integer()
        if ret == "":
            self.throw_parse_error("Expected an integer, found %s" %
                    self.peek_to_whitespace())
        self.take_chars(len(ret))
        return ret

    def parse_comment_line(self):
        if self.peek_char() is None:
            return ""
        if self.peek_char() != "#":
            return None
        comment = self.current_line[self.index:]
        self.new_line()
        return comment


class Recipe(object):

    def __init__(self, f):
        self.base_branch = _RecipeParser(f).parse()
