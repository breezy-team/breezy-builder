# bzr-builder: a bzr plugin to constuct trees based on recipes
# Copyright 2010 Canonical Ltd.

# This program is free software: you can redistribute it and/or modify it 
# under the terms of the GNU General Public License version 3, as published 
# by the Free Software Foundation.

# This program is distributed in the hope that it will be useful, but 
# WITHOUT ANY WARRANTY; without even the implied warranties of 
# MERCHANTABILITY, SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR 
# PURPOSE.  See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along 
# with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Copies/backports features from more recent versions of packages

This allows bzr-builder to continue to work with older breezy and python-debian
versions while using features from newer versions.
"""

# NOTE FOR DEVELOPERS: with each backport please include a comment saying which
# version of what you are backporting from, to make it easier to copy bugfixes
# made in later version (and so that we know which things we can drop from this
# module if bzr-builder ever raises which package versions it depends on).

import os
import pwd
import re
import socket

from breezy.merge import (
    Merger,
    Merge3Merger,
    )
from breezy import (
    errors,
    generate_ids,
    osutils,
    revision as _mod_revision,
    transform,
    ui,
    )

# Backport of breezy.merge.MergeIntoMerger, introduced in bzr 2.2rc1.
# (Also backports PathNotInTree, _MergeTypeParameterizer, MergeIntoMergeType)
class PathNotInTree(errors.BzrError):

    _fmt = """Merge-into failed because %(tree)s does not contain %(path)s."""

    def __init__(self, path, tree):
        errors.BzrError.__init__(self, path=path, tree=tree)


class MergeIntoMerger(Merger):
    """Merger that understands other_tree will be merged into a subdir.

    This also changes the Merger api so that it uses real Branch, revision_id,
    and RevisonTree objects, rather than using revision specs.
    """

    def __init__(self, this_tree, other_branch, other_tree, target_subdir,
            source_subpath, other_rev_id=None):
        """Create a new MergeIntoMerger object.

        source_subpath in other_tree will be effectively copied to
        target_subdir in this_tree.

        :param this_tree: The tree that we will be merging into.
        :param other_branch: The Branch we will be merging from.
        :param other_tree: The RevisionTree object we want to merge.
        :param target_subdir: The relative path where we want to merge
            other_tree into this_tree
        :param source_subpath: The relative path specifying the subtree of
            other_tree to merge into this_tree.
        """
        # It is assumed that we are merging a tree that is not in our current
        # ancestry, which means we are using the "EmptyTree" as our basis.
        null_ancestor_tree = this_tree.branch.repository.revision_tree(
                                _mod_revision.NULL_REVISION)
        super(MergeIntoMerger, self).__init__(
            this_branch=this_tree.branch,
            this_tree=this_tree,
            other_tree=other_tree,
            base_tree=null_ancestor_tree,
            )
        self._target_subdir = target_subdir
        self._source_subpath = source_subpath
        self.other_branch = other_branch
        if other_rev_id is None:
            other_rev_id = other_tree.get_revision_id()
        self.other_rev_id = self.other_basis = other_rev_id
        self.base_is_ancestor = True
        self.backup_files = True
        self.merge_type = Merge3Merger
        self.show_base = False
        self.reprocess = False
        self.interesting_ids = None
        self.merge_type = _MergeTypeParameterizer(MergeIntoMergeType,
              target_subdir=self._target_subdir,
              source_subpath=self._source_subpath)
        if self._source_subpath != '':
            # If this isn't a partial merge make sure the revisions will be
            # present.
            self._maybe_fetch(self.other_branch, self.this_branch,
                self.other_basis)

    def set_pending(self):
        if self._source_subpath != '':
            return
        Merger.set_pending(self)


class _MergeTypeParameterizer(object):
    """Wrap a merge-type class to provide extra parameters.
    
    This is hack used by MergeIntoMerger to pass some extra parameters to its
    merge_type.  Merger.do_merge() sets up its own set of parameters to pass to
    the 'merge_type' member.  It is difficult override do_merge without
    re-writing the whole thing, so instead we create a wrapper which will pass
    the extra parameters.
    """

    def __init__(self, merge_type, **kwargs):
        self._extra_kwargs = kwargs
        self._merge_type = merge_type

    def __call__(self, *args, **kwargs):
        kwargs.update(self._extra_kwargs)
        return self._merge_type(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._merge_type, name)


class MergeIntoMergeType(Merge3Merger):
    """Merger that incorporates a tree (or part of a tree) into another."""

    # Backport note: the definition of _finish_computing_transform is copied
    # from Merge3Merger in bzr 2.2 (it is supposed to be inherited from
    # Merge3Merger, but was only introduced in 2.2).
    def _finish_computing_transform(self):
        """Finalize the transform and report the changes.

        This is the second half of _compute_transform.
        """
        child_pb = ui.ui_factory.nested_progress_bar()
        try:
            fs_conflicts = transform.resolve_conflicts(self.tt, child_pb,
                lambda t, c: transform.conflict_pass(t, c, self.other_tree))
        finally:
            child_pb.finished()
        if self.change_reporter is not None:
            from breezy import delta
            delta.report_changes(
                self.tt.iter_changes(), self.change_reporter)
        self.cook_conflicts(fs_conflicts)
        from breezy import trace
        for conflict in self.cooked_conflicts:
            trace.warning(conflict)

    def __init__(self, *args, **kwargs):
        """Initialize the merger object.

        :param args: See Merge3Merger.__init__'s args.
        :param kwargs: See Merge3Merger.__init__'s keyword args, except for
            source_subpath and target_subdir.
        :keyword source_subpath: The relative path specifying the subtree of
            other_tree to merge into this_tree.
        :keyword target_subdir: The relative path where we want to merge
            other_tree into this_tree
        """
        # All of the interesting work happens during Merge3Merger.__init__(),
        # so we have have to hack in to get our extra parameters set.
        self._source_subpath = kwargs.pop('source_subpath')
        self._target_subdir = kwargs.pop('target_subdir')
        super(MergeIntoMergeType, self).__init__(*args, **kwargs)

    def _compute_transform(self):
        child_pb = ui.ui_factory.nested_progress_bar()
        try:
            entries = self._entries_to_incorporate()
            entries = list(entries)
            for num, (entry, parent_id) in enumerate(entries):
                child_pb.update('Preparing file merge', num, len(entries))
                parent_trans_id = self.tt.trans_id_file_id(parent_id)
                trans_id = transform.new_by_entry(self.tt, entry,
                    parent_trans_id, self.other_tree)
        finally:
            child_pb.finished()
        self._finish_computing_transform()

    def _entries_to_incorporate(self):
        """Yields pairs of (inventory_entry, new_parent)."""
        other_inv = self.other_tree.inventory
        subdir_id = other_inv.path2id(self._source_subpath)
        if subdir_id is None:
            # XXX: The error would be clearer if it gave the URL of the source
            # branch, but we don't have a reference to that here.
            raise PathNotInTree(self._source_subpath, "Source tree")
        subdir = other_inv[subdir_id]
        parent_in_target = osutils.dirname(self._target_subdir)
        target_id = self.this_tree.inventory.path2id(parent_in_target)
        if target_id is None:
            raise PathNotInTree(self._target_subdir, "Target tree")
        name_in_target = osutils.basename(self._target_subdir)
        merge_into_root = subdir.copy()
        merge_into_root.name = name_in_target
        if merge_into_root.file_id in self.this_tree.inventory:
            # Give the root a new file-id.
            # This can happen fairly easily if the directory we are
            # incorporating is the root, and both trees have 'TREE_ROOT' as
            # their root_id.  Users will expect this to Just Work, so we
            # change the file-id here.
            # Non-root file-ids could potentially conflict too.  That's really
            # an edge case, so we don't do anything special for those.  We let
            # them cause conflicts.
            merge_into_root.file_id = generate_ids.gen_file_id(name_in_target)
        yield (merge_into_root, target_id)
        if subdir.kind != 'directory':
            # No children, so we are done.
            return
        for ignored_path, entry in other_inv.iter_entries_by_dir(subdir_id):
            parent_id = entry.parent_id
            if parent_id == subdir.file_id:
                # The root's parent ID has changed, so make sure children of
                # the root refer to the new ID.
                parent_id = merge_into_root.file_id
            yield (entry, parent_id)


def get_maintainer():
    """Create maintainer string using the same algorithm as in dch.

    From version 0.1.19 python-debian has this function in debian.changelog 
    """
    env = os.environ
    regex = re.compile(r"^(.*)\s+<(.*)>$")

    # Split email and name
    if 'DEBEMAIL' in env:
        match_obj = regex.match(env['DEBEMAIL'])
        if match_obj:
            if not 'DEBFULLNAME' in env:
                env['DEBFULLNAME'] = match_obj.group(1)
            env['DEBEMAIL'] = match_obj.group(2)
    if 'DEBEMAIL' not in env or 'DEBFULLNAME' not in env:
        if 'EMAIL' in env:
            match_obj = regex.match(env['EMAIL'])
            if match_obj:
                if not 'DEBFULLNAME' in env:
                    env['DEBFULLNAME'] = match_obj.group(1)
                env['EMAIL'] = match_obj.group(2)

    # Get maintainer's name
    if 'DEBFULLNAME' in env:
        maintainer = env['DEBFULLNAME']
    elif 'NAME' in env:
        maintainer = env['NAME']
    else:
        # Use password database if no data in environment variables
        try:
            maintainer = re.sub(r',.*', '', pwd.getpwuid(os.getuid()).pw_gecos)
        except (KeyError, AttributeError):
            # TBD: Use last changelog entry value
            maintainer = "bzr-builder"

    # Get maintainer's mail address
    if 'DEBEMAIL' in env:
        email = env['DEBEMAIL']
    elif 'EMAIL' in env:
        email = env['EMAIL']
    else:
        addr = None
        if os.path.exists('/etc/mailname'):
            f = open('/etc/mailname')
            try:
                addr = f.readline().strip()
            finally:
                f.close()
        if not addr:
            addr = socket.getfqdn()
        if addr:
            user = pwd.getpwuid(os.getuid()).pw_name
            if not user:
                addr = None
            else:
                addr = "%s@%s" % (user, addr)

        if addr:
            email = addr
        else:
            # TBD: Use last changelog entry value
            email = "none@example.org"

    return (maintainer, email)
