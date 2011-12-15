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

from bzrlib import (
    errors,
    lazy_regex,
    )

from bzrlib.plugins.builder.recipe import (
    BranchSubstitutionVariable,
    SubstitutionUnavailable,
    branch_vars,
    simple_vars,
    )


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

    minimum_format = 0.4

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


class DebUpstreamBaseVariable(DebUpstreamVariable):

    basename = "debupstream-base"
    version_regex = lazy_regex.lazy_compile(r'([~+])(svn[0-9]+|bzr[0-9]+|git[0-9a-f]+)')
    minimum_format = 0.4

    def get(self):
        version = super(DebUpstreamBaseVariable, self).get()
        version = self.version_regex.sub("\\1", version)
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



