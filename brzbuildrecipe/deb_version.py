# bzr-builder: a bzr plugin to constuct trees based on recipes
# Copyright 2009-2011 Canonical Ltd.

# This program is free software: you can redistribute it and/or modify it 
# under the terms of the GNU General Public License version 3, as published 
# by the Free Software Foundation.

# This program is distributed in the hope that it will be useful, but 
# WITHOUT ANY WARRANTY; without even the implied warranties of 
# MERCHANTABILITY, SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR 
# PURPOSE.  See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.

from breezy import (
    errors,
    lazy_regex,
    )

from .recipe import (
    BranchSubstitutionVariable,
    DateVariable,
    GitCommitVariable,
    LatestTagVariable,
    RevdateVariable,
    RevtimeVariable,
    RevnoVariable,
    SubstitutionUnavailable,
    SubversionRevnumVariable,
    TimeVariable,
    branch_vars,
    simple_vars,
    )
try:
    from debian import changelog
except ImportError:
    # In older versions of python-debian the main package was named 
    # debian_bundle
    from debian_bundle import changelog


class DebUpstreamVariable(BranchSubstitutionVariable):

    basename = "debupstream"

    minimum_format = 0.1

    def __init__(self, branch_name, version):
        super(DebUpstreamVariable, self).__init__(branch_name)
        self._version = version

    @classmethod
    def from_changelog(cls, branch_name, changelog):
        if len(changelog._blocks) > 0:
            return cls(branch_name, changelog._blocks[0].version)
        else:
            return cls(branch_name, None)

    def get(self):
        if self._version is None:
            raise SubstitutionUnavailable(self.name,
                "No previous changelog to take the upstream version from")
        # Should we include the epoch?
        return self._version.upstream_version


class DebVersionVariable(BranchSubstitutionVariable):

    basename = "debversion"

    minimum_format = 0.3

    def __init__(self, branch_name, version):
        super(DebVersionVariable, self).__init__(branch_name)
        self._version = version

    @classmethod
    def from_changelog(cls, branch_name, changelog):
        if len(changelog._blocks) > 0:
            return cls(branch_name, changelog._blocks[0].version)
        else:
            return cls(branch_name, None)

    def get(self):
        if self._version is None:
            raise SubstitutionUnavailable(self.name,
                "No previous changelog to take the version from")
        return str(self._version)

dfsg_regex = lazy_regex.lazy_compile(
    r'[+.]*dfsg[.]*[0-9]+')

version_regex = lazy_regex.lazy_compile(
    r'([~+])(svn[0-9]+|bzr[0-9]+|git[0-9a-f]+)')

def version_extract_base(version):
    version = dfsg_regex.sub("", version)
    return version_regex.sub("\\1", version)


class DebUpstreamBaseVariable(DebUpstreamVariable):

    basename = "debupstream-base"
    minimum_format = 0.3

    def get(self):
        version = super(DebUpstreamBaseVariable, self).get()
        version = version_extract_base(version)
        if version[-1] not in ("~", "+"):
            version += "+"
        return version


ok_to_preserve = [DebUpstreamVariable, DebUpstreamBaseVariable,
    DebVersionVariable]
deb_branch_vars = [DebVersionVariable, DebUpstreamBaseVariable, DebUpstreamVariable]


def check_expanded_deb_version(base_branch):
    checked_version = base_branch.deb_version
    if checked_version is None:
        return
    for token in ok_to_preserve:
        if issubclass(token, BranchSubstitutionVariable):
            for name in base_branch.list_branch_names():
                checked_version = checked_version.replace(
                    token.determine_name(name), "")
            checked_version = checked_version.replace(
                    token.determine_name(None), "")
        else:
            checked_version = checked_version.replace(
                token.name, "")
    if "{" in checked_version:
        available_tokens = [var.name for var in simple_vars if
                            var.available_in(base_branch.format)]
        for var_kls in branch_vars + deb_branch_vars:
            if not var_kls.available_in(base_branch.format):
                continue
            for name in base_branch.list_branch_names():
                available_tokens.append(var_kls.determine_name(name))
            available_tokens.append(var_kls.determine_name(None))
        raise errors.BzrCommandError("deb-version not fully "
                "expanded: %s. Valid substitutions in recipe format %s are: %s"
                % (base_branch.deb_version, base_branch.format,
                    available_tokens))


def substitute_branch_vars(base_branch, branch_name, branch, revid):
    """Substitute the branch variables for the given branch name in deb_version.

    Where deb_version has a place to substitute the revno for a branch
    this will substitute it for the given branch name.

    :param branch_name: the name of the RecipeBranch to substitute.
    :param branch: Branch object for the branch
    :param revid: Revision id in the branch for which to return the revno
    """
    if base_branch.deb_version is None:
        return
    revno_var = RevnoVariable(branch_name, branch, revid)
    base_branch.deb_version = revno_var.replace(base_branch.deb_version)
    if base_branch.format < 0.4:
        # The other variables were introduced in recipe format 0.4
        return
    svn_revno_var = SubversionRevnumVariable(branch_name, branch, revid)
    base_branch.deb_version = svn_revno_var.replace(base_branch.deb_version)
    git_commit_var = GitCommitVariable(branch_name, branch, revid)
    base_branch.deb_version = git_commit_var.replace(base_branch.deb_version)
    latest_tag_var = LatestTagVariable(branch_name, branch, revid)
    base_branch.deb_version = latest_tag_var.replace(base_branch.deb_version)
    revdate_var = RevdateVariable(branch_name, branch, revid)
    base_branch.deb_version = revdate_var.replace(base_branch.deb_version)
    revtime_var = RevtimeVariable(branch_name, branch, revid)
    base_branch.deb_version = revtime_var.replace(base_branch.deb_version)
    tree = branch.repository.revision_tree(revid)
    if tree.has_filename('debian/changelog'):
        with tree.lock_read():
            cl = changelog.Changelog(tree.get_file_text('debian/changelog'))
            substitute_changelog_vars(base_branch, branch_name, cl)


def substitute_changelog_vars(base_branch, branch_name, changelog):
    """Substitute variables related from a changelog.

    :param branch_name: Branch name (None for root branch)
    :param changelog: Changelog object to use
    """
    from .deb_version import DebUpstreamVariable, DebUpstreamBaseVariable, DebVersionVariable
    debupstream_var = DebUpstreamVariable.from_changelog(branch_name, changelog)
    base_branch.deb_version = debupstream_var.replace(base_branch.deb_version)
    if base_branch.format < 0.3:
        # The other variables were introduced in recipe format 0.4
        return
    debupstreambase_var = DebUpstreamBaseVariable.from_changelog(
        branch_name, changelog)
    base_branch.deb_version = debupstreambase_var.replace(base_branch.deb_version)
    pkgversion_var = DebVersionVariable.from_changelog(branch_name, changelog)
    base_branch.deb_version = pkgversion_var.replace(base_branch.deb_version)


def substitute_time(base_branch, time):
    """Substitute the time in to deb_version if needed.

    :param time: a datetime.datetime with the desired time.
    """
    if base_branch.deb_version is None:
        return
    base_branch.deb_version = TimeVariable(time).replace(base_branch.deb_version)
    base_branch.deb_version = DateVariable(time).replace(base_branch.deb_version)
