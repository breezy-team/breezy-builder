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
import signal
import subprocess
import time

from breezy import (
    branch as _mod_branch,
    controldir,
    errors,
    merge,
    revision,
    revisionspec,
    tag,
    trace,
    transport,
    urlutils,
    version_info as bzr_version_info,
    )

try:
    from breezy.errors import NoWhoami
except ImportError:
    NoWhoami = object()


try:
    MergeIntoMerger = merge.MergeIntoMerger
except (AttributeError, NameError):
    from .backports import MergeIntoMerger


def subprocess_setup():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)


MERGE_INSTRUCTION = "merge"
NEST_PART_INSTRUCTION = "nest-part"
NEST_INSTRUCTION = "nest"
RUN_INSTRUCTION = "run"
USAGE = {
    MERGE_INSTRUCTION: 'merge NAME BRANCH [REVISION]',
    NEST_INSTRUCTION: 'nest NAME BRANCH TARGET-DIR [REVISION]',
    NEST_PART_INSTRUCTION:
        'nest-part NAME BRANCH SUBDIR [TARGET-DIR [REVISION]]',
    RUN_INSTRUCTION: 'run COMMAND',
    }

SAFE_INSTRUCTIONS = [
    MERGE_INSTRUCTION, NEST_PART_INSTRUCTION, NEST_INSTRUCTION]


class SubstitutionUnavailable(errors.BzrError):
    _fmt = """Substitution for %(name)s not available: %(reason)s"""

    def __init__(self, name, reason):
        errors.BzrError.__init__(self, name=name, reason=reason)


class SubstitutionVariable(object):
    """A substitution variable for a version string."""

    def replace(self, value):
        """Replace name with value."""
        raise NotImplementedError(self.replace)

    @classmethod
    def available_in(cls, format):
        """Check if this variable is available in a particular format."""
        raise NotImplementedError(cls.available_in)


class SimpleSubstitutionVariable(SubstitutionVariable):

    name = None

    minimum_format = None

    def replace(self, value):
        if not self.name in value:
            return value
        return value.replace(self.name, self.get())

    def get(self):
        raise NotImplementedError(self.value)

    @classmethod
    def available_in(self, format):
        return (format >= self.minimum_format)


class BranchSubstitutionVariable(SimpleSubstitutionVariable):

    basename = None

    def __init__(self, branch_name=None):
        super(BranchSubstitutionVariable, self).__init__()
        self.branch_name = branch_name

    @classmethod
    def determine_name(cls, branch_name):
        if branch_name is None:
            return "{%s}" % cls.basename
        else:
            return "{%s:%s}" % (cls.basename, branch_name)

    @property
    def name(self):
        return self.determine_name(self.branch_name)


class TimeVariable(SimpleSubstitutionVariable):

    name = "{time}"

    minimum_format = 0.1

    def __init__(self, time):
        self._time = time

    def get(self):
        return self._time.strftime("%Y%m%d%H%M")


class DateVariable(SimpleSubstitutionVariable):

    name = "{date}"

    minimum_format = 0.1

    def __init__(self, time):
        self._time = time

    def get(self):
        return self._time.strftime("%Y%m%d")


class RevisionVariable(BranchSubstitutionVariable):

    minimum_format = 0.1

    def __init__(self, branch_name, branch, revid):
        super(RevisionVariable, self).__init__(branch_name)
        self.branch = branch
        self.revid = revid


class RevnoVariable(RevisionVariable):

    basename = "revno"

    minimum_format = 0.1

    def get_revno(self):
        try:
            revno = self.branch.revision_id_to_revno(self.revid)
            return str(revno)
        except errors.NoSuchRevision:
            # We need to load and use the full revno map after all
            result = self.branch.get_revision_id_to_revno_map().get(
                    self.revid)
        if result is None:
            return result
        return ".".join(result)

    def get(self):
        revno = self.get_revno()
        if revno is None:
            raise errors.BzrCommandError("Can't substitute revno of "
                    "branch %s in deb-version, as it's revno can't be "
                    "determined" % revno)
        return revno


class RevtimeVariable(RevisionVariable):

    basename = "revtime"

    minimum_format = 0.4

    def get(self):
        rev = self.branch.repository.get_revision(self.revid)
        return time.strftime("%Y%m%d%H%M", time.gmtime(rev.timestamp))


class RevdateVariable(RevisionVariable):

    basename = "revdate"

    minimum_format = 0.4

    def get(self):
        rev = self.branch.repository.get_revision(self.revid)
        return time.strftime("%Y%m%d", time.gmtime(rev.timestamp))


def extract_svn_revnum(rev):
    try:
        foreign_revid = rev.foreign_revid
    except AttributeError:
        try:
            (mapping_name, uuid, bp, srevnum) = rev.revision_id.split(":", 3)
        except ValueError:
            raise errors.InvalidRevisionId(rev.revision_id, None)
        if not mapping_name.startswith("svn-"):
            raise errors.InvalidRevisionId(rev.revision_id, None)
        return int(srevnum)
    else:
        if rev.mapping.vcs.abbreviation == "svn":
            return foreign_revid[2]
        else:
            raise errors.InvalidRevisionId(rev.revision_id, None)


class SubversionRevnumVariable(RevisionVariable):

    basename = "svn-revno"

    minimum_format = 0.4

    def get(self):
        rev = self.branch.repository.get_revision(self.revid)
        try:
            revno = extract_svn_revnum(rev)
        except errors.InvalidRevisionId:
            raise errors.BzrCommandError("unable to expand %s for %r in %r: "
                "not a Subversion revision" % (
                    self.name, self.revid, self.branch))
        return str(revno)


def extract_git_foreign_revid(rev):
    try:
        foreign_revid = rev.foreign_revid
    except AttributeError:
        try:
            (mapping_name, foreign_revid) = rev.revision_id.split(":", 1)
        except ValueError:
            raise errors.InvalidRevisionId(rev.revision_id, None)
        if not mapping_name.startswith("git-"):
            raise errors.InvalidRevisionId(rev.revision_id, None)
        return foreign_revid
    else:
        if rev.mapping.vcs.abbreviation == "git":
            return foreign_revid
        else:
            raise errors.InvalidRevisionId(rev.revision_id, None)


class GitCommitVariable(RevisionVariable):

    basename = "git-commit"

    minimum_format = 0.4

    def get(self):
        rev = self.branch.repository.get_revision(self.revid)
        try:
            commit_sha = extract_git_foreign_revid(rev)
        except errors.InvalidRevisionId:
            raise errors.BzrCommandError("unable to expand %s for %r in %r: "
                "not a Git revision" % (
                    self.name, self.revid, self.branch))
        return commit_sha[:7]


class LatestTagVariable(RevisionVariable):

    basename = "latest-tag"

    minimum_format = 0.4

    def get(self):
        reverse_tag_dict = self.branch.tags.get_reverse_tag_dict()
        self.branch.lock_read()
        try:
            graph = self.branch.repository.get_graph()
            for revid in graph.iter_lefthand_ancestry(self.revid):
                if revid in reverse_tag_dict:
                    return reverse_tag_dict[revid][0]
            else:
                raise errors.BzrCommandError("No tags set on branch %s mainline" %
                    self.branch_name)
        finally:
            self.branch.unlock()


branch_vars = [RevnoVariable, SubversionRevnumVariable,
    GitCommitVariable, LatestTagVariable, RevdateVariable,
    RevtimeVariable]
simple_vars = [TimeVariable, DateVariable]


class CommandFailedError(errors.BzrError):

    _fmt = "The command \"%(command)s\" failed."

    def __init__(self, command):
        super(CommandFailedError, self).__init__()
        self.command = command


def ensure_basedir(to_transport):
    """Ensure that the basedir of to_transport exists.

    It is allowed to already exist currently, to reuse directories.

    :param to_transport: The Transport to ensure that the basedir of
            exists.
    """
    try:
        to_transport.mkdir('.')
    except errors.FileExists:
        pass
    except errors.NoSuchFile:
        raise errors.BzrCommandError('Parent of "%s" does not exist.'
                                     % to_transport.base)


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
        ensure_basedir(to_transport)
        dir = br_from.controldir.sprout(to_transport.base, revision_id,
                                    possible_transports=possible_transports,
                                    accelerator_tree=accelerator_tree,
                                    source_branch=br_from,
                                    stacked=(bzr_version_info >= (2, 3, 0)))
        try:
            tree_to = dir.open_workingtree()
        except errors.NoWorkingTree:
            # There's no working tree, so it's probably in a no-trees repo,
            # but the whole point of this is to create trees, so we should
            # forcibly create one.
            tree_to = dir.create_workingtree()
        br_to = tree_to.branch
        created_br_to = True
        br_from.tags.merge_to(br_to.tags)
        created_tree_to = True
    else:
        # We do a "pull"
        if tree_to is not None:
            # FIXME: should these pulls overwrite?
            tree_to.pull(br_from, stop_revision=revision_id,
                    possible_transports=possible_transports)
        else:
            br_to.pull(br_from, stop_revision=revision_id,
                    possible_transports=possible_transports)
            tree_to = br_to.controldir.create_workingtree()
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


def merge_branch(child_branch, tree_to, br_to, possible_transports=None):
    """Merge the branch specified by child_branch.

    :param child_branch: the RecipeBranch to retrieve the branch and revision to
            merge from.
    :param tree_to: the WorkingTree to merge in to.
    :param br_to: the Branch to merge in to.
    """
    if child_branch.branch is None:
        child_branch.branch = _mod_branch.Branch.open(child_branch.url,
                possible_transports=possible_transports)
    child_branch.branch.lock_read()
    try:
        child_branch.branch.tags.merge_to(br_to.tags)
        if child_branch.revspec is not None:
            merge_revspec = revisionspec.RevisionSpec.from_string(
                    child_branch.revspec)
            try:
                merge_revid = merge_revspec.as_revision_id(
                    child_branch.branch)
            except errors.InvalidRevisionSpec, e:
                # Give the user a hint if they didn't mean to speciy
                # a revspec.
                e.extra = (". Did you not mean to specify a revspec "
                    "at the end of the merge line?")
                raise e
        else:
            merge_revid = child_branch.branch.last_revision()
        child_branch.revid = merge_revid
        try:
            merger = merge.Merger.from_revision_ids(tree_to, merge_revid,
                    other_branch=child_branch.branch, tree_branch=br_to)
        except errors.UnrelatedBranches:
            # Let's just try and hope for the best.
            merger = merge.Merger.from_revision_ids(tree_to, merge_revid,
                    other_branch=child_branch.branch, tree_branch=br_to,
                    base=revision.NULL_REVISION)
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
        config = br_to.get_config()
        try:
            committer = config.username()
        except NoWhoami:
            committer = "bzr-builder <nobody@example.com>"
        tree_to.commit("Merge %s" %
                urlutils.unescape_for_display(child_branch.url, 'utf-8'),
                committer=committer)
    finally:
        child_branch.branch.unlock()


def nest_part_branch(child_branch, tree_to, br_to, subpath, target_subdir=None):
    """Merge the branch subdirectory specified by child_branch.

    :param child_branch: the RecipeBranch to retrieve the branch and revision to
            merge from.
    :param tree_to: the WorkingTree to merge in to.
    :param br_to: the Branch to merge in to.
    :param subpath: only merge files from branch that are from this path.
        e.g. subpath='/debian' will only merge changes from that directory.
    :param target_subdir: (optional) directory in target to merge that
        subpath into.  Defaults to basename of subpath.
    """
    child_branch.branch = _mod_branch.Branch.open(child_branch.url)
    child_branch.branch.lock_read()
    try:
        child_branch.resolve_revision_id()
        other_tree = child_branch.branch.basis_tree()
        other_tree.lock_read()
        try:
            if target_subdir is None:
                target_subdir = os.path.basename(subpath)
            # Create any missing parent directories
            target_subdir_parent = os.path.dirname(target_subdir)
            missing = []
            while tree_to.path2id(target_subdir_parent) is None:
                missing.append(target_subdir_parent)
                target_subdir_parent = os.path.dirname(target_subdir_parent)
            for path in reversed(missing):
                tree_to.mkdir(path)
            merger = MergeIntoMerger(this_tree=tree_to, other_tree=other_tree,
                other_branch=child_branch.branch, target_subdir=target_subdir,
                source_subpath=subpath, other_rev_id=child_branch.revid)
            merger.set_base_revision(revision.NULL_REVISION, child_branch.branch)
            conflict_count = merger.do_merge()
            merger.set_pending()
        finally:
            other_tree.unlock()
    finally:
        child_branch.branch.unlock()

    if conflict_count:
        # FIXME: better reporting
        raise errors.BzrCommandError("Conflicts from merge")
    tree_to.commit("Merge %s of %s" %
        (subpath, urlutils.unescape_for_display(child_branch.url, 'utf-8')))


def update_branch(base_branch, tree_to, br_to, to_transport,
        possible_transports=None):
    if base_branch.branch is None:
        base_branch.branch = _mod_branch.Branch.open(base_branch.url,
                possible_transports=possible_transports)
    base_branch.branch.lock_read()
    try:
        base_branch.resolve_revision_id()
        tree_to, br_to = pull_or_branch(tree_to, br_to, base_branch.branch,
                to_transport, base_branch.revid,
                possible_transports=possible_transports)
    finally:
        base_branch.branch.unlock()
    return tree_to, br_to


def _resolve_revisions_recurse(new_branch, substitute_branch_vars,
        if_changed_from=None):
    changed = False
    new_branch.branch = _mod_branch.Branch.open(new_branch.url)
    new_branch.branch.lock_read()
    try:
        new_branch.resolve_revision_id()
        if substitute_branch_vars is not None:
            substitute_branch_vars(new_branch.name, new_branch.branch, new_branch.revid)
        if (if_changed_from is not None
                and (new_branch.revspec is not None
                        or if_changed_from.revspec is not None)):
            if if_changed_from.revspec is not None:
                changed_revspec = revisionspec.RevisionSpec.from_string(
                        if_changed_from.revspec)
                changed_revision_id = changed_revspec.as_revision_id(
                        new_branch.branch)
            else:
                changed_revision_id = new_branch.branch.last_revision()
            if new_branch.revid != changed_revision_id:
                changed = True
        for index, instruction in enumerate(new_branch.child_branches):
            child_branch = instruction.recipe_branch
            if_changed_child = None
            if if_changed_from is not None:
                if_changed_child = if_changed_from.child_branches[index].recipe_branch
            if child_branch is not None:
                child_changed = _resolve_revisions_recurse(child_branch,
                        substitute_branch_vars,
                        if_changed_from=if_changed_child)
                if child_changed:
                    changed = child_changed
        return changed
    finally:
        new_branch.branch.unlock()


def resolve_revisions(base_branch, if_changed_from=None, substitute_branch_vars=None):
    """Resolve all the unknowns in base_branch.

    This walks the RecipeBranch and calls substitute_branch_vars for
    each child branch.

    If if_changed_from is not None then it should be a second RecipeBranch
    to compare base_branch against. If the shape, or the revision ids differ
    then the function will return True.

    :param base_branch: the RecipeBranch we plan to build.
    :param if_changed_from: the RecipeBranch that we want to compare against.
    :param substitute_branch_vars: Callable called for
        each branch with (name, bzr branch and last revision)
    :return: False if if_changed_from is not None, and the shape and revisions
        of the two branches don't differ. True otherwise.
    """
    changed = False
    if if_changed_from is not None:
        changed = base_branch.different_shape_to(if_changed_from)
    if_changed_from_revisions = if_changed_from
    if changed:
        if_changed_from_revisions = None

    if substitute_branch_vars is not None:
        real_subsitute_branch_vars = lambda n, b, r: substitute_branch_vars(base_branch, n, b, r)
    else:
        real_subsitute_branch_vars = None
    changed_revisions = _resolve_revisions_recurse(base_branch,
            real_subsitute_branch_vars,
            if_changed_from=if_changed_from_revisions)
    if not changed:
        changed = changed_revisions
    if if_changed_from is not None and not changed:
        return False
    return True


def _build_inner_tree(base_branch, target_path, possible_transports=None):
    revision_of = ""
    if base_branch.revspec is not None:
        revision_of = "revision '%s' of " % base_branch.revspec
    trace.note("Retrieving %s'%s' to put at '%s'."
        % (revision_of, base_branch.url, target_path))
    to_transport = transport.get_transport(target_path,
            possible_transports=possible_transports)
    try:
        tree_to, br_to = controldir.ControlDir.open_tree_or_branch(target_path)
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
            tree_to, br_to = update_branch(base_branch, tree_to, br_to,
                    to_transport, possible_transports=possible_transports)
            for instruction in base_branch.child_branches:
                instruction.apply(target_path, tree_to, br_to)
        finally:
            # Is this ok if tree_to is created by pull_or_branch?
            if br_to is not None:
                br_to.unlock()
    finally:
        if tree_to is not None:
            tree_to.unlock()


def build_tree(base_branch, target_path, possible_transports=None):
    """Build the RecipeBranch at a path.

    Follow the instructions embodied in RecipeBranch and build a tree
    based on them rooted at target_path. If target_path exists and
    is the root of the branch then the branch will be updated based on
    what the RecipeBranch requires.

    :param base_branch: a RecipeBranch to build.
    :param target_path: the path to the base of the desired output.
    """
    trace.note("Building tree.")
    _build_inner_tree(base_branch, target_path,
            possible_transports=possible_transports)


class ChildBranch(object):
    """A child branch in a recipe.

    If the nest path is not None it is the path relative to the recipe branch
    where the child branch should be placed.  If it is None then the child
    branch should be merged instead of nested.
    """

    can_have_children = False

    def __init__(self, recipe_branch, nest_path=None):
        self.recipe_branch = recipe_branch
        self.nest_path = nest_path

    def apply(self, target_path, tree_to, br_to, possible_transports=None):
        raise NotImplementedError(self.apply)

    def as_tuple(self):
        return (self.recipe_branch, self.nest_path)

    def _get_revid_part(self):
        if self.recipe_branch.revid is not None:
            revid_part = " revid:%s" % self.recipe_branch.revid
        elif self.recipe_branch.revspec is not None:
            revid_part = " %s" % self.recipe_branch.revspec
        else:
            revid_part = ""
        return revid_part

    def __repr__(self):
        return "<%s %r>" % (self.__class__.__name__, self.nest_path)


class CommandInstruction(ChildBranch):

    def apply(self, target_path, tree_to, br_to, possible_transports=None):
        # it's a command
        trace.note("Running '%s' in '%s'." % (self.nest_path, target_path))
        proc = subprocess.Popen(self.nest_path, cwd=target_path,
            preexec_fn=subprocess_setup, shell=True, stdin=subprocess.PIPE)
        proc.communicate()
        if proc.returncode != 0:
            raise CommandFailedError(self.nest_path)

    def as_text(self):
        return "%s %s" % (RUN_INSTRUCTION, self.nest_path)


class MergeInstruction(ChildBranch):

    def apply(self, target_path, tree_to, br_to, possible_transports=None):
        revision_of = ""
        if self.recipe_branch.revspec is not None:
            revision_of = "revision '%s' of " % self.recipe_branch.revspec
        trace.note("Merging %s'%s' in to '%s'."
                % (revision_of, self.recipe_branch.url, target_path))
        merge_branch(self.recipe_branch, tree_to, br_to,
                possible_transports=possible_transports)

    def as_text(self):
        revid_part = self._get_revid_part()
        return "%s %s %s%s" % (
            MERGE_INSTRUCTION, self.recipe_branch.name,
            self.recipe_branch.url, revid_part)

    def __repr__(self):
        return "<%s %r>" % (self.__class__.__name__, self.recipe_branch.name)


class NestPartInstruction(ChildBranch):

    def __init__(self, recipe_branch, subpath, target_subdir):
        ChildBranch.__init__(self, recipe_branch)
        self.subpath = subpath
        self.target_subdir = target_subdir

    def apply(self, target_path, tree_to, br_to):
        nest_part_branch(self.recipe_branch, tree_to, br_to, self.subpath,
            self.target_subdir)

    def as_text(self):
        revid_part = self._get_revid_part()
        if revid_part:
            target_subdir = self.target_subdir
            if target_subdir is None:
                target_subdir = self.subpath
            target_revid_part = " %s%s" % (
                target_subdir, revid_part)
        elif self.target_subdir is not None:
            target_revid_part = " %s" % self.target_subdir
        else:
            target_revid_part = ""
        return "%s %s %s %s%s" % (
            NEST_PART_INSTRUCTION, self.recipe_branch.name,
            self.recipe_branch.url, self.subpath, target_revid_part)


class NestInstruction(ChildBranch):

    can_have_children = True

    def apply(self, target_path, tree_to, br_to, possible_transports=None):
        _build_inner_tree(self.recipe_branch,
            target_path=os.path.join(target_path, self.nest_path),
            possible_transports=possible_transports)

    def as_text(self):
        revid_part = self._get_revid_part()
        return "%s %s %s %s%s" % (
            NEST_INSTRUCTION, self.recipe_branch.name,
            self.recipe_branch.url, self.nest_path, revid_part)

    def __repr__(self):
        return "<%s %r>" % (self.__class__.__name__,
            self.recipe_branch.name)


class RecipeBranch(object):
    """A nested structure that represents a Recipe.

    A RecipeBranch has a name and a url (the name can be None for the
    root branch), and optionally child branches that are either merged
    or nested.

    The child_branches attribute is a list of tuples of ChildBranch objects.
    The revid attribute records the revid that the url and revspec resolved
    to when the RecipeBranch was built, or None if it has not been built.

    :ivar revid: after this recipe branch has been built this is set to the
        revision ID that was merged/nested from the branch at self.url.
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
        self.branch = None

    def resolve_revision_id(self):
        """Resolve the revision id for this branch.
        """
        if self.revspec is not None:
            revspec = revisionspec.RevisionSpec.from_string(self.revspec)
            revision_id = revspec.as_revision_id(self.branch)
        else:
            revision_id = self.branch.last_revision()
        self.revid = revision_id

    def merge_branch(self, branch):
        """Merge a child branch in to this one.

        :param branch: the RecipeBranch to merge.
        """
        self.child_branches.append(MergeInstruction(branch))

    def nest_part_branch(self, branch, subpath=None, target_subdir=None):
        """Merge subdir of a child branch into this one.

        :param branch: the RecipeBranch to merge.
        :param subpath: only merge files from branch that are from this path.
            e.g. subpath='/debian' will only merge changes from that directory.
        :param target_subdir: (optional) directory in target to merge that
            subpath into.  Defaults to basename of subpath.
        """
        self.child_branches.append(
            NestPartInstruction(branch, subpath, target_subdir))

    def nest_branch(self, location, branch):
        """Nest a child branch in to this one.

        :param location: the relative path at which this branch should be nested.
        :param branch: the RecipeBranch to nest.
        """
        assert location not in [b.nest_path for b in self.child_branches],\
            "%s already has branch nested there" % location
        self.child_branches.append(NestInstruction(branch, location))

    def run_command(self, command):
        """Set a command to be run.

        :param command: the command to be run
        """
        self.child_branches.append(CommandInstruction(None, command))

    def different_shape_to(self, other_branch):
        """Tests whether the name, url and child_branches are the same"""
        if self.name != other_branch.name:
            return True
        if self.url != other_branch.url:
            return True
        if len(self.child_branches) != len(other_branch.child_branches):
            return True
        for index, instruction in enumerate(self.child_branches):
            child_branch = instruction.recipe_branch
            nest_location = instruction.nest_path
            other_instruction = other_branch.child_branches[index]
            other_child_branch = other_instruction.recipe_branch
            other_nest_location = other_instruction.nest_path
            if nest_location != other_nest_location:
                return True
            if ((child_branch is None and other_child_branch is not None)
                    or (child_branch is not None and other_child_branch is None)):
                return True
            # if child_branch is None then other_child_branch must be
            # None too, meaning that they are both run instructions,
            # we would compare their nest locations (commands), but
            # that has already been done, so just guard
            if (child_branch is not None
                    and child_branch.different_shape_to(other_child_branch)):
                return True
        return False

    def iter_all_instructions(self):
        """Iter over all instructions under this branch."""
        for instruction in self.child_branches:
            yield instruction
            child_branch = instruction.recipe_branch
            if child_branch is None:
                continue
            for instruction in child_branch.iter_all_instructions():
                yield instruction

    def iter_all_branches(self):
        """Iterate over all branches."""
        yield self
        for instruction in self.child_branches:
            child_branch = instruction.recipe_branch
            if child_branch is None:
                continue
            for subbranch in child_branch.iter_all_branches():
                yield subbranch

    def lookup_branch(self, name):
        """Lookup a branch by its name."""
        for branch in self.iter_all_branches():
            if branch.name == name:
                return branch
        else:
            raise KeyError(name)

    def list_branch_names(self):
        """List all of the branch names under this one.

        :return: a list of the branch names.
        :rtype: list(str)
        """
        return [branch.name for branch in self.iter_all_branches()
                if branch.name is not None]

    def __repr__(self):
        return "<%s %r>" % (self.__class__.__name__, self.name)


class BaseRecipeBranch(RecipeBranch):
    """The RecipeBranch that is at the root of a recipe."""

    def __init__(self, url, deb_version, format, revspec=None):
        """Create a BaseRecipeBranch.

        :param deb_version: the template to use for the version number.
                Should be None for anything except the root branch.
        """
        super(BaseRecipeBranch, self).__init__(None, url, revspec=revspec)
        self.deb_version = deb_version
        self.format = format

    def _add_child_branches_to_manifest(self, child_branches, indent_level):
        manifest = ""
        for instruction in child_branches:
            manifest += "%s%s\n" % (
                "  " * indent_level, instruction.as_text())
            if instruction.can_have_children:
                manifest += self._add_child_branches_to_manifest(
                    instruction.recipe_branch.child_branches,
                    indent_level+1)
        return manifest

    def __str__(self):
        return self.get_recipe_text(validate=True)

    def get_recipe_text(self, validate=False):
        manifest = "# bzr-builder format %s" % str(self.format)
        if self.deb_version is not None:
            # TODO: should we store the expanded version that was used?
            manifest += " deb-version %s" % (self.deb_version,)
        manifest += "\n"
        if self.revid is not None:
            manifest += "%s revid:%s\n" % (self.url, self.revid)
        elif self.revspec is not None:
            manifest += "%s %s\n" % (self.url, self.revspec)
        else:
            manifest += "%s\n" % (self.url,)
        manifest += self._add_child_branches_to_manifest(self.child_branches,
                0)
        if validate:
            # Sanity check.
            # TODO: write a function that compares the result of this parse with
            # the branch that we built it from.
            RecipeParser(manifest).parse()
        return manifest


class RecipeParseError(errors.BzrError):
    _fmt = "Error parsing %(filename)s:%(line)s:%(char)s: %(problem)s."

    def __init__(self, filename, line, char, problem):
        errors.BzrError.__init__(self, filename=filename, line=line, char=char,
                problem=problem)


class InstructionParseError(RecipeParseError):
    _fmt = RecipeParseError._fmt + "\nUsage: %(usage)s"

    def __init__(self, filename, line, char, problem, instruction):
        RecipeParseError.__init__(self, filename, line, char, problem)
        self.usage = USAGE[instruction]


class ForbiddenInstructionError(RecipeParseError):

    def __init__(self, filename, line, char, problem, instruction_name=None):
        RecipeParseError.__init__(self, filename, line, char, problem)
        self.instruction_name = instruction_name


class RecipeParser(object):
    """Parse a recipe.

    The parse() method is probably the only one that interests you.
    """

    whitespace_chars = " \t"
    eol_char = "\n"
    digit_chars = ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9")

    NEWEST_VERSION = 0.4

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

    def parse(self, permitted_instructions=None):
        """Parse the recipe.

        :param permitted_instructions: a list of instructions that you
            want to allow. Defaults to None allowing them all.
        :type permitted_instructions: list(str) or None
        :return: a RecipeBranch representing the recipe.
        """
        self.lines = self.text.split("\n")
        self.index = 0
        self.line_index = 0
        self.current_line = self.lines[self.line_index]
        self.current_indent_level = 0
        self.seen_nicks = set()
        self.seen_paths = {".": 1}
        (version, deb_version) = self.parse_header()
        self.version = version
        last_instruction = None
        active_branches = []
        last_branch = None
        while self.line_index < len(self.lines):
            if self.is_blankline():
                self.new_line()
                continue
            comment = self.parse_comment_line()
            if comment is not None:
                self.new_line()
                continue
            old_indent_level = self.parse_indent()
            if old_indent_level is not None:
                if (old_indent_level < self.current_indent_level
                    and last_instruction != NEST_INSTRUCTION):
                    self.throw_parse_error("Not allowed to indent unless "
                            "after a '%s' line" % NEST_INSTRUCTION)
                if old_indent_level < self.current_indent_level:
                    active_branches.append(last_branch)
                else:
                    unindent = self.current_indent_level - old_indent_level
                    active_branches = active_branches[:unindent]
            if last_instruction is None:
                url = self.take_to_whitespace("branch to start from")
                revspec = self.parse_optional_revspec()
                self.new_line()
                last_branch = BaseRecipeBranch(url, deb_version,
                        self.version, revspec=revspec)
                active_branches = [last_branch]
                last_instruction = ""
            else:
                instruction = self.parse_instruction(
                    permitted_instructions=permitted_instructions)
                if instruction == RUN_INSTRUCTION:
                    self.parse_whitespace("the command",
                        instruction=instruction)
                    command = self.take_to_newline().strip()
                    self.new_line()
                    active_branches[-1].run_command(command)
                else:
                    branch_id = self.parse_branch_id(instruction)
                    url = self.parse_branch_url(instruction)
                    if instruction == NEST_INSTRUCTION:
                        location = self.parse_branch_location(instruction)
                    if instruction == NEST_PART_INSTRUCTION:
                        path = self.parse_subpath(instruction)
                        target_subdir = self.parse_optional_path()
                        if target_subdir == '':
                            target_subdir = None
                            revspec = None
                        else:
                            revspec = self.parse_optional_revspec()
                    else:
                        revspec = self.parse_optional_revspec()
                    self.new_line(instruction)
                    last_branch = RecipeBranch(branch_id, url, revspec=revspec)
                    if instruction == NEST_INSTRUCTION:
                        active_branches[-1].nest_branch(location, last_branch)
                    elif instruction == MERGE_INSTRUCTION:
                        active_branches[-1].merge_branch(last_branch)
                    elif instruction == NEST_PART_INSTRUCTION:
                        active_branches[-1].nest_part_branch(
                            last_branch, path, target_subdir)
                last_instruction = instruction
        if len(active_branches) == 0:
            self.throw_parse_error("Empty recipe")
        return active_branches[0]

    def parse_header(self):
        self.parse_char("#")
        self.parse_word("bzr-builder", require_whitespace=False)
        self.parse_word("format")
        version, version_str = self.peek_float("format version")
        if version > self.NEWEST_VERSION:
            self.throw_parse_error("Unknown format: '%s'" % str(version))
        self.take_chars(len(version_str))
        deb_version = self.parse_optional_deb_version()
        self.new_line()
        return version, deb_version

    def parse_instruction(self, permitted_instructions=None):
        if self.version < 0.2:
            options = (MERGE_INSTRUCTION, NEST_INSTRUCTION)
            options_str = "'%s' or '%s'" % options
        elif self.version < 0.3:
            options = (MERGE_INSTRUCTION, NEST_INSTRUCTION, RUN_INSTRUCTION)
            options_str = "'%s', '%s' or '%s'" % options
        else:
            options = (MERGE_INSTRUCTION, NEST_INSTRUCTION,
                NEST_PART_INSTRUCTION, RUN_INSTRUCTION)
            options_str = "'%s', '%s', '%s' or '%s'" % options
        instruction = self.peek_to_whitespace()
        if instruction is None:
            self.throw_parse_error("End of line while looking for %s"
                    % options_str)
        if instruction in options:
            if permitted_instructions is not None:
                if instruction not in permitted_instructions:
                    self.throw_parse_error("The '%s' instruction is "
                            "forbidden" % instruction,
                            cls=ForbiddenInstructionError,
                            instruction_name=instruction)
            self.take_chars(len(instruction))
            return instruction
        self.throw_parse_error("Expecting %s, got '%s'"
                % (options_str, instruction))

    def parse_branch_id(self, instruction):
        self.parse_whitespace("the branch id", instruction=instruction)
        branch_id = self.peek_to_whitespace()
        if branch_id is None:
            self.throw_parse_error("End of line while looking for the "
                    "branch id", cls=InstructionParseError,
                    instruction=instruction)
        if branch_id in self.seen_nicks:
            self.throw_parse_error("'%s' was already used to identify "
                    "a branch." % branch_id)
        self.take_chars(len(branch_id))
        self.seen_nicks.add(branch_id)
        return branch_id

    def parse_branch_url(self, instruction):
        self.parse_whitespace("the branch url", instruction=instruction)
        branch_url = self.take_to_whitespace("the branch url", instruction)
        return branch_url

    def parse_branch_location(self, instruction):
        # FIXME: Needs a better term
        self.parse_whitespace("the location to nest")
        location = self.peek_to_whitespace()
        if location is None:
            self.throw_parse_error("End of line while looking for the "
                    "location to nest", cls=InstructionParseError,
                    instruction=instruction)
        norm_location = os.path.normpath(location)
        if norm_location in self.seen_paths:
            self.throw_parse_error("The path '%s' is a duplicate of "
                    "the one used on line %d." % (location,
                        self.seen_paths[norm_location]),
                    InstructionParseError, instruction=instruction)
        if os.path.isabs(norm_location):
            self.throw_parse_error("Absolute paths are not allowed: %s"
                    % location, InstructionParseError, instruction=instruction)
        if norm_location.startswith(".."):
            self.throw_parse_error("Paths outside the current directory "
                    "are not allowed: %s" % location,
                    cls=InstructionParseError, instruction=instruction)
        self.take_chars(len(location))
        self.seen_paths[norm_location] = self.line_index + 1
        return location

    def parse_subpath(self, instruction):
        self.parse_whitespace("the subpath to merge", instruction=instruction)
        location = self.take_to_whitespace("the subpath to merge", instruction)
        return location

    def parse_revspec(self):
        self.parse_whitespace("the revspec")
        revspec = self.take_to_whitespace("the revspec")
        return revspec

    def parse_optional_deb_version(self):
        self.parse_whitespace("'deb-version'", require=False)
        actual = self.peek_to_whitespace()
        if actual is None:
            # End of line, no version
            return None
        if actual != "deb-version":
            self.throw_expecting_error("deb-version", actual)
        self.take_chars(len("deb-version"))
        self.parse_whitespace("a value for 'deb-version'")
        return self.take_to_whitespace("a value for 'deb-version'")

    def parse_optional_revspec(self):
        self.parse_whitespace(None, require=False)
        revspec = self.peek_to_whitespace()
        if revspec is not None:
            self.take_chars(len(revspec))
        return revspec

    def parse_optional_path(self):
        self.parse_whitespace(None, require=False)
        path = self.peek_to_whitespace()
        if path is not None:
            self.take_chars(len(path))
        return path

    def throw_parse_error(self, problem, cls=None, **kwargs):
        if cls is None:
            cls = RecipeParseError
        raise cls(self.filename, self.line_index + 1,
                self.index + 1, problem, **kwargs)

    def throw_expecting_error(self, expected, actual):
        self.throw_parse_error("Expecting '%s', got '%s'"
                % (expected, actual))

    def throw_eol(self, expected):
        self.throw_parse_error("End of line while looking for '%s'" % expected)

    def new_line(self, instruction=None):
        # Jump over any whitespace
        self.parse_whitespace(None, require=False)
        remaining = self.peek_to_whitespace()
        if remaining != None:
            kwargs = {}
            if instruction is not None:
                kwargs = {
                    'cls': InstructionParseError,
                    'instruction': instruction}
            self.throw_parse_error("Expecting the end of the line, got '%s'"
                    % remaining, **kwargs)
        self.index = 0
        self.line_index += 1
        if self.line_index >= len(self.lines):
            self.current_line = None
        else:
            self.current_line = self.lines[self.line_index]

    def is_blankline(self):
        whitespace = self.peek_whitespace()
        if whitespace is None:
            return True
        return self.peek_char(skip=len(whitespace)) is None

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

    def parse_whitespace(self, looking_for, require=True, instruction=None):
        if require:
            actual = self.peek_char()
            if actual is None:
                kwargs = {}
                if instruction is not None:
                    kwargs = {
                        'cls': InstructionParseError,
                        'instruction': instruction,
                        }
                self.throw_parse_error("End of line while looking for "
                        "%s" % looking_for, **kwargs)
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

    def peek_whitespace(self):
        ret = ""
        char = self.peek_char()
        if char is None:
            return char
        count = 0
        while char is not None and char in self.whitespace_chars:
            ret += char
            count += 1
            char = self.peek_char(skip=count)
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

    def take_to_whitespace(self, looking_for, instruction=None):
        text = self.peek_to_whitespace()
        if text is None:
            kwargs = {}
            if instruction is not None:
                kwargs = {
                    'cls': InstructionParseError,
                    'instruction': instruction}
            self.throw_parse_error("End of line while looking for %s"
                    % looking_for, **kwargs)
        self.take_chars(len(text))
        return text

    def peek_float(self, looking_for):
        self.parse_whitespace(looking_for)
        ret = self._parse_integer()
        conv_fn = int
        if ret == "":
            self.throw_parse_error("Expecting a float, got '%s'" %
                    self.peek_to_whitespace())
        if self.peek_char(skip=len(ret)) == ".":
            conv_fn = float
            ret2 = self._parse_integer(skip=len(ret)+1)
            if ret2 == "":
                self.throw_parse_error("Expecting a float, got '%s'" %
                    self.peek_to_whitespace())
            ret += "." + ret2
        try:
            fl = conv_fn(ret)
        except ValueError:
            self.throw_parse_error("Expecting a float, got '%s'" % ret)
        return (fl, ret)

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

    def take_to_newline(self):
        text = self.current_line[self.index:]
        self.index += len(text)
        return text

    def parse_comment_line(self):
        whitespace = self.peek_whitespace()
        if whitespace is None:
            return ""
        if self.peek_char(skip=len(whitespace)) is None:
            return ""
        if self.peek_char(skip=len(whitespace)) != "#":
            return None
        self.parse_whitespace(None, require=False)
        comment = self.current_line[self.index:]
        self.index += len(comment)
        return comment
