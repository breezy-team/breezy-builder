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
        branch,
        bzrdir,
        errors,
        merge,
        revisionspec,
        tag,
        transport,
        ui,
        urlutils,
        workingtree,
        )


def ensure_basedir(to_location):
    """Ensure that the basedir of to_location exists.

    It is allowed to already exist currently, to reuse directories.

    :param to_location: The path to ensure exists.
    :return: a Transport for that location
    """
    to_transport = transport.get_transport(to_location)
    try:
        to_transport.mkdir('.')
    except errors.FileExists:
        pass
    except errors.NoSuchFile:
        raise errors.BzrCommandError('Parent of "%s" does not exist.'
                                     % to_location)
    return to_transport


def pull_or_branch(tree_to, br_to, br_from, to_transport, revision_id,
        accelerator_tree=None, possible_transports=None):
    """Either pull or branch from a branch.

    Depending on whether the target branch and tree exist already this
    will either pull from the source branch, or branch from it. If it
    returns this function will return a branch and tree for the target,
    after creating either if necessary.

    :param tree_to: The WorkingTree to pull in to, or None. If not None then
            br_to must not be None.
    :param br_to: The Branch to pull in to, or None to branch.
    :param br_from: The Branch to pull/branch from.
    :param to_transport: A Transport for the root of the target.
    :param revision_id: the revision id to pull/branch.
    :param accelerator_tree: A tree to take contents from that is faster than
            extracting from br_from, or None.
    :param possible_transports: A list of transports that can be reused, or
            None.
    :return: A tuple of (target tree, target branch) which are the updated
            tree and branch, created if necessary. They are locked, and you
            should use these instead of tree_to and br_to if they were passed
            in, including for unlocking.
    """
    created_tree_to = False
    created_br_to = False
    if br_to is None:
        # We do a "branch"
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
            result = tree_to.pull(br_from, stop_revision=revision_id,
                    possible_transports=possible_transports)
        else:
            result = br_to.pull(br_from, stop_revision=revision_id,
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


def merge_branch(child_branch, tree_to, br_to):
    merge_from = branch.Branch.open(child_branch.url)
    merge_from.lock_read()
    try:
        pb = ui.ui_factory.nested_progress_bar()
        try:
            tag._merge_tags_if_possible(merge_from, br_to)
            if child_branch.revspec is not None:
                merge_revspec = revisionspec.RevisionSpec.from_string(
                        child_branch.revspec)
                merge_revid = merge_revspec.as_revision_id(merge_from)
            else:
                merge_revid = merge_from.last_revision()
            child_branch.revid = merge_revid
            merger = merge.Merger.from_revision_ids(pb, tree_to, merge_revid,
                    other_branch=merge_from, tree_branch=br_to)
            merger.merge_type = merge.Merge3Merger
            if (merger.base_rev_id == merger.other_rev_id and
                    merger.other_rev_id is not None):
                # Nothing to do.
                return
            conflict_count = merger.do_merge()
            merger.set_pending()
            if conflict_count:
                # FIXME: better reporting
                raise errors.BzrCommandError("Conflicts from merge")
            tree_to.commit("Merge %s" %
                    urlutils.unescape_for_display(
                        child_branch.url, 'utf-8'))
        finally:
            pb.finished()
    finally:
        merge_from.unlock()


def build_tree(base_branch, target_path):
    """Build the RecipeBranch at a path.

    Follow the instructions embodied in RecipeBranch and build a tree
    based on them rooted at target_path. If target_path exists and
    is the root of the branch then the branch will be updated based on
    what the RecipeBranch requires.

    :param base_branch: a RecipeBranch to build.
    :param target_path: the path to the base of the desired output.
    """
    to_transport = ensure_basedir(target_path)
    try:
        tree_to, br_to = bzrdir.BzrDir.open_tree_or_branch(target_path)
        # Should we commit any changes in the tree here? If we don't
        # then they will get folded up in to the first merge.
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
                if base_branch.revspec is not None:
                    revspec = revisionspec.RevisionSpec.from_string(
                            base_branch.revspec)
                    revision_id = revspec.as_revision_id(br_from)
                else:
                    revision_id = br_from.last_revision()
                base_branch.revid = revision_id
                tree_to, br_to = pull_or_branch(tree_to, br_to, br_from,
                        to_transport, revision_id,
                        accelerator_tree=accelerator_tree,
                        possible_transports=[to_transport])
            finally:
                br_from.unlock()
            for child_branch, nest_location in base_branch.child_branches:
                if nest_location is not None:
                    # FIXME: pass possible_transports around
                    build_tree(child_branch,
                            target_path=os.path.join(target_path,
                                nest_location))
                else:
                    merge_branch(child_branch, tree_to, br_to)
        finally:
            # Is this ok if tree_to is created by pull_or_branch
            if br_to is not None:
                br_to.unlock()
    finally:
        if tree_to is not None:
            tree_to.unlock()


class RecipeBranch(object):
    """A nested structure that represents a Recipe.

    A RecipeBranch has a name and a url (the name can be None for the
    root branch), and optionally child branches that are either merged
    or nested.

    The child_branches attribute is a list of tuples of (RecipeBranch,
    relative path), where if the relative branch is not None it is the
    path relative to this branch where the child branch should be placed.
    If it is None then the child branch should be merged instead.

    The revid attribute records the revid that the url and revspec resolved
    to when the RecipeBranch was built, or None if it has not been built.
    """

    def __init__(self, name, url, revspec=None):
        """Create a RecipeBranch.

        :param name: the name for the branch, or None if it is the root.
        :param url: the URL from which to retrieve the branch.
        :param revspec: a revision specifier for the revision of the branch
                to use, or None (the default) to use the last revision.
        """
        self.name = name
        self.url = url
        self.revspec = revspec
        self.child_branches = []
        self.revid = None

    def merge_branch(self, branch):
        """Merge a child branch in to this one.

        :param branch: the RecipeBranch to merge.
        """
        self.child_branches.append((branch, None))

    def nest_branch(self, location, branch):
        """Nest a child branch in to this one.

        :parm location: the relative path at which this branch should be nested.
        :param branch: the RecipeBranch to nest.
        """
        assert location not in [b[1] for b in self.child_branches],\
            "%s already has branch nested there" % location
        self.child_branches.append((branch, location))


class RecipeParseError(errors.BzrError):
    _fmt = "Error parsing %(filename)s:%(line)s:%(char)s: %(problem)s."

    def __init__(self, filename, line, char, problem):
        errors.BzrError.__init__(self, filename=filename, line=line, char=char,
                problem=problem)


class RecipeParser(object):
    """Parse a recipe.

    The parse() method is probably the only one that interests you.
    """

    whitespace_chars = " \t"
    eol_char = "\n"
    digit_chars = ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9")

    def __init__(self, f, filename=None):
        """Create a RecipeParser.

        :param f: either the recipe as a string, or a file like object to
            take it from.
        :param filename: the filename of the recipe if known (for error
            reporting).
        """
        if getattr(f, "read", None) is not None:
            self.text = f.read()
        else:
            self.text = f
        self.filename = filename
        if filename is None:
            self.filename = "recipe"

    def parse(self):
        """Parse the recipe.

        :return: a RecipeBranch representing the recipe.
        """
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
                revspec = self.parse_optional_revspec()
                self.new_line()
                last_branch = RecipeBranch(None, url, revspec=revspec)
                active_branches = [last_branch]
                last_instruction = ""
            else:
                instruction = self.parse_instruction()
                branch_id = self.parse_branch_id()
                url = self.parse_branch_url()
                if instruction == "nest":
                    location = self.parse_branch_location()
                revspec = self.parse_optional_revspec()
                self.new_line()
                last_branch = RecipeBranch(branch_id, url, revspec=revspec)
                if instruction == "nest":
                    active_branches[-1].nest_branch(location, last_branch)
                else:
                    active_branches[-1].merge_branch(last_branch)
                last_instruction = instruction
        if len(active_branches) == 0:
            self.throw_parse_error("Empty recipe")
        return active_branches[0]

    def parse_header(self):
        self.parse_char("#")
        self.parse_word("bzr-builder", require_whitespace=False)
        self.parse_word("format")
        version = self.parse_float("format version")
        self.parse_word("deb-version")
        self.parse_whitespace("a value for 'deb-version'")
        deb_version = self.take_to_whitespace("a value for 'deb-version'")
        self.new_line()

    def parse_instruction(self):
        instruction = self.peek_to_whitespace()
        if instruction is None:
            self.throw_parse_error("End of line while looking for 'nest' "
                    "or 'merge'")
        if instruction == "nest" or instruction == "merge":
            self.take_chars(len(instruction))
            return instruction
        self.throw_parse_error("Expecting 'nest' or 'merge', got '%s'"
                % instruction)

    def parse_branch_id(self):
        self.parse_whitespace("the branch id")
        branch_id = self.take_to_whitespace("the branch id")
        return branch_id

    def parse_branch_url(self):
        self.parse_whitespace("the branch url")
        branch_url = self.take_to_whitespace("the branch url")
        return branch_url

    def parse_branch_location(self):
        # FIXME: Needs a better term
        self.parse_whitespace("the location to nest")
        location = self.take_to_whitespace("the location to nest")
        return location

    def parse_optional_revspec(self):
        self.parse_whitespace(None, require=False)
        revspec = self.peek_to_whitespace()
        if revspec is not None:
            self.take_chars(len(revspec))
        return revspec

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
        self.parse_whitespace(None, require=False)
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

    def parse_char(self, char):
        actual = self.peek_char()
        if actual is None:
            self.throw_eol(char)
        if actual == char:
            self.take_char()
            return char
        self.throw_expecting_error(char, actual)

    def parse_indent(self):
        """Parse the indent from the start of the line."""
        # FIXME: should just peek the whitespace
        new_indent = self.parse_whitespace(None, require=False)
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

    def parse_whitespace(self, looking_for, require=True):
        if require:
            actual = self.peek_char()
            if actual is None:
                self.throw_parse_error("End of line while looking for "
                        "%s" % looking_for)
            if actual not in self.whitespace_chars:
                self.throw_parse_error("Expecting whitespace before %s, "
                        "got '%s'." % (looking_for, actual))
        ret = ""
        actual = self.peek_char()
        while (actual is not None and actual in self.whitespace_chars):
            self.take_char()
            ret += actual
            actual = self.peek_char()
        return ret

    def parse_word(self, expected, require_whitespace=True):
        self.parse_whitespace("'%s'" % expected, require=require_whitespace)
        length = len(expected)
        actual = self.peek_to_whitespace()
        if actual == expected:
            self.take_chars(length)
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

    def parse_float(self, looking_for):
        self.parse_whitespace(looking_for)
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
