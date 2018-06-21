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

import datetime
import textwrap

from breezy import (
    errors,
    )
from breezy.tests import (
    TestCase,
    TestCaseWithTransport,
    )
from ..deb_version import (
    DebUpstreamBaseVariable,
    DebUpstreamVariable,
    DebVersionVariable,
    SubstitutionUnavailable,
    check_expanded_deb_version,
    version_extract_base,
    substitute_branch_vars,
    substitute_time,
    )
from ..recipe import (
    BaseRecipeBranch,
    RecipeBranch,
    resolve_revisions,
    )

try:
    from debian import changelog
except ImportError:
    # In older versions of python-debian the main package was named 
    # debian_bundle
    from debian_bundle import changelog


class ResolveRevisionsTests(TestCaseWithTransport):

    def test_unchanged(self):
        source =self.make_branch_and_tree("source")
        revid = source.commit("one")
        branch1 = BaseRecipeBranch("source", "{revno}", 0.2, revspec="1")
        branch2 = BaseRecipeBranch("source", "{revno}", 0.2,
                revspec="revid:%s" % revid)
        self.assertEqual(False, resolve_revisions(branch1,
            if_changed_from=branch2,
            substitute_branch_vars=substitute_branch_vars))
        self.assertEqual("source", branch1.url)
        self.assertEqual(revid, branch1.revid)
        self.assertEqual("1", branch1.revspec)
        self.assertEqual("1", branch1.deb_version)

    def test_unchanged_not_explicit(self):
        source =self.make_branch_and_tree("source")
        revid = source.commit("one")
        branch1 = BaseRecipeBranch("source", "{revno}", 0.2)
        branch2 = BaseRecipeBranch("source", "{revno}", 0.2,
                revspec="revid:%s" % revid)
        self.assertEqual(False, resolve_revisions(branch1,
            if_changed_from=branch2,
            substitute_branch_vars=substitute_branch_vars))
        self.assertEqual("source", branch1.url)
        self.assertEqual(revid, branch1.revid)
        self.assertEqual(None, branch1.revspec)
        self.assertEqual("1", branch1.deb_version)

    def test_unchanged_multilevel(self):
        source =self.make_branch_and_tree("source")
        revid = source.commit("one")
        branch1 = BaseRecipeBranch("source", "{revno}", 0.2)
        branch2 = RecipeBranch("nested1", "source")
        branch3 = RecipeBranch("nested2", "source")
        branch2.nest_branch("bar", branch3)
        branch1.nest_branch("foo", branch2)
        branch4 = BaseRecipeBranch("source", "{revno}", 0.2,
                revspec="revid:%s" % revid)
        branch5 = RecipeBranch("nested1", "source",
                revspec="revid:%s" % revid)
        branch6 = RecipeBranch("nested2", "source",
                revspec="revid:%s" % revid)
        branch5.nest_branch("bar", branch6)
        branch4.nest_branch("foo", branch5)
        self.assertEqual(False, resolve_revisions(branch1,
                if_changed_from=branch4,
                substitute_branch_vars=substitute_branch_vars))
        self.assertEqual("source", branch1.url)
        self.assertEqual(revid, branch1.revid)
        self.assertEqual(None, branch1.revspec)
        self.assertEqual("1", branch1.deb_version)

    def test_changed(self):
        source =self.make_branch_and_tree("source")
        revid = source.commit("one")
        branch1 = BaseRecipeBranch("source", "{revno}", 0.2, revspec="1")
        branch2 = BaseRecipeBranch("source", "{revno}", 0.2,
                revspec="revid:foo")
        self.assertEqual(True, resolve_revisions(branch1,
            if_changed_from=branch2,
            substitute_branch_vars=substitute_branch_vars))
        self.assertEqual("source", branch1.url)
        self.assertEqual(revid, branch1.revid)
        self.assertEqual("1", branch1.revspec)
        self.assertEqual("1", branch1.deb_version)

    def test_changed_shape(self):
        source =self.make_branch_and_tree("source")
        revid = source.commit("one")
        branch1 = BaseRecipeBranch("source", "{revno}", 0.2, revspec="1")
        branch2 = BaseRecipeBranch("source", "{revno}", 0.2,
                revspec="revid:%s" % revid)
        branch3 = RecipeBranch("nested", "source")
        branch1.nest_branch("foo", branch3)
        self.assertEqual(True, resolve_revisions(branch1,
            if_changed_from=branch2,
            substitute_branch_vars=substitute_branch_vars))
        self.assertEqual("source", branch1.url)
        self.assertEqual(revid, branch1.revid)
        self.assertEqual("1", branch1.revspec)
        self.assertEqual("1", branch1.deb_version)

    def test_changed_command(self):
        source =self.make_branch_and_tree("source")
        source.commit("one")
        branch1 = BaseRecipeBranch("source", "{revno}", 0.2)
        branch2 = BaseRecipeBranch("source", "{revno}", 0.2)
        branch1.run_command("touch test1")
        branch2.run_command("touch test2")
        self.assertEqual(True, resolve_revisions(branch1,
            if_changed_from=branch2,
            substitute_branch_vars=substitute_branch_vars))
        self.assertEqual("source", branch1.url)

    def test_unchanged_command(self):
        source =self.make_branch_and_tree("source")
        source.commit("one")
        branch1 = BaseRecipeBranch("source", "{revno}", 0.2)
        branch2 = BaseRecipeBranch("source", "{revno}", 0.2)
        branch1.run_command("touch test1")
        branch2.run_command("touch test1")
        self.assertEqual(False, resolve_revisions(branch1,
            if_changed_from=branch2,
            substitute_branch_vars=substitute_branch_vars))
        self.assertEqual("source", branch1.url)

    def test_substitute(self):
        source =self.make_branch_and_tree("source")
        revid1 = source.commit("one")
        source.commit("two")
        branch1 = BaseRecipeBranch("source",
                "{revno}-{revno:packaging}", 0.2, revspec="1")
        branch2 = RecipeBranch("packaging", "source")
        branch1.nest_branch("debian", branch2)
        self.assertEqual(True, resolve_revisions(branch1,
           substitute_branch_vars=substitute_branch_vars))
        self.assertEqual("source", branch1.url)
        self.assertEqual(revid1, branch1.revid)
        self.assertEqual("1", branch1.revspec)
        self.assertEqual("1-2", branch1.deb_version)

    def test_substitute_supports_debupstream(self):
        # resolve_revisions should leave debupstream parameters alone and not
        # complain.
        source =self.make_branch_and_tree("source")
        source.commit("one")
        source.commit("two")
        branch1 = BaseRecipeBranch("source", "{debupstream}-{revno}", 0.2)
        resolve_revisions(branch1,
            substitute_branch_vars=substitute_branch_vars)
        self.assertEqual("{debupstream}-2", branch1.deb_version)

    def test_subsitute_not_fully_expanded(self):
        source =self.make_branch_and_tree("source")
        source.commit("one")
        source.commit("two")
        branch1 = BaseRecipeBranch("source", "{revno:packaging}", 0.2)
        resolve_revisions(branch1, substitute_branch_vars=substitute_branch_vars)
        self.assertRaises(errors.BzrCommandError, check_expanded_deb_version, branch1)

    def test_substitute_svn_not_svn(self):
        br = self.make_branch("source")
        source = br.create_checkout("checkout")
        source.commit("one")
        source.commit("two")
        branch1 = BaseRecipeBranch("source", "foo-{svn-revno}", 0.4)
        e = self.assertRaises(errors.BzrCommandError, resolve_revisions,
            branch1, None, substitute_branch_vars)
        self.assertTrue(str(e).startswith("unable to expand {svn-revno} "),
            e)

    def test_substitute_svn(self):
        br = self.make_branch("source")
        source = br.create_checkout("checkout")
        source.commit("one")
        source.commit("two",
            rev_id="svn-v4:be7e6eca-30d4-0310-a8e5-ac0d63af7070:trunk:5344")
        branch1 = BaseRecipeBranch("source", "foo-{svn-revno}", 0.4)
        resolve_revisions(branch1, substitute_branch_vars=substitute_branch_vars)
        self.assertEqual("foo-5344", branch1.deb_version)

    def test_substitute_git_not_git(self):
        source = self.make_branch_and_tree("source")
        source.commit("one")
        source.commit("two")
        branch1 = BaseRecipeBranch("source", "foo-{git-commit}", 0.4)
        e = self.assertRaises(errors.BzrCommandError, resolve_revisions,
            branch1, None, substitute_branch_vars)
        self.assertTrue(str(e).startswith("unable to expand {git-commit} "),
            e)

    def test_substitute_git(self):
        source = self.make_branch_and_tree("source")
        source.commit("one", 
            rev_id="git-v1:a029d7b2cc83c26a53d8b2a24fa12c340fcfac58")
        branch1 = BaseRecipeBranch("source", "foo-{git-commit}", 0.4)
        resolve_revisions(branch1,
            substitute_branch_vars=substitute_branch_vars)
        self.assertEqual("foo-a029d7b", branch1.deb_version)

    def test_latest_tag(self):
        source = self.make_branch_and_tree("source")
        revid = source.commit("one")
        source.branch.tags.set_tag("millbank", revid)
        source.commit("two")
        branch1 = BaseRecipeBranch("source", "foo-{latest-tag}", 0.4)
        resolve_revisions(branch1,
            substitute_branch_vars=substitute_branch_vars)
        self.assertEqual("foo-millbank", branch1.deb_version)

    def test_latest_tag_no_tag(self):
        source = self.make_branch_and_tree("source")
        revid = source.commit("one")
        source.commit("two")
        branch1 = BaseRecipeBranch("source", "foo-{latest-tag}", 0.4)
        e = self.assertRaises(errors.BzrCommandError,
            resolve_revisions, branch1,
            substitute_branch_vars=substitute_branch_vars)
        self.assertTrue(str(e).startswith("No tags set on branch None mainline"),
            e)

    def test_substitute_revdate(self):
        br = self.make_branch("source")
        source = br.create_checkout("checkout")
        source.commit("one")
        source.commit("two", timestamp=1307708628, timezone=0)
        branch1 = BaseRecipeBranch("source", "foo-{revdate}", 0.4)
        resolve_revisions(branch1,
                substitute_branch_vars=substitute_branch_vars)
        self.assertEqual("foo-20110610", branch1.deb_version)

    def test_substitute_revtime(self):
        br = self.make_branch("source")
        source = br.create_checkout("checkout")
        source.commit("one")
        source.commit("two", timestamp=1307708628, timezone=0)
        branch1 = BaseRecipeBranch("source", "foo-{revtime}", 0.4)
        resolve_revisions(branch1,
                substitute_branch_vars=substitute_branch_vars)
        self.assertEqual("foo-201106101223", branch1.deb_version)


class DebUpstreamVariableTests(TestCase):

    def write_changelog(self, version):
        contents = textwrap.dedent("""
            package (%s) experimental; urgency=low

              * Initial release. (Closes: #XXXXXX)

             -- Jelmer Vernooij <jelmer@debian.org>  Thu, 19 May 2011 10:07:41 +0100
            """ % version)[1:]
        return changelog.Changelog(file=contents)

    def test_empty_changelog(self):
        var = DebUpstreamVariable.from_changelog(None, changelog.Changelog())
        self.assertRaises(SubstitutionUnavailable, var.get)

    def test_version(self):
        var = DebUpstreamVariable.from_changelog(None,
            self.write_changelog("2.3"))
        self.assertEquals("2.3", var.get())

    def test_epoch(self):
        # The epoch is (currently) ignored by {debupstream}.
        var = DebUpstreamVariable.from_changelog(None,
            self.write_changelog("2:2.3"))
        self.assertEquals("2.3", var.get())

    def test_base_without_snapshot(self):
        var = DebUpstreamBaseVariable.from_changelog(None,
            self.write_changelog("2.4"))
        self.assertEquals("2.4+", var.get())

    def test_base_with_svn_snapshot(self):
        var = DebUpstreamBaseVariable.from_changelog(None,
            self.write_changelog("2.4~svn4"))
        self.assertEquals("2.4~", var.get())

    def test_base_with_bzr_snapshot(self):
        var = DebUpstreamBaseVariable.from_changelog(None,
            self.write_changelog("2.4+bzr343"))
        self.assertEquals("2.4+", var.get())


class VersionExtractBaseTests(TestCase):

    def test_simple_extract(self):
        self.assertEquals("2.4", version_extract_base("2.4"))
        self.assertEquals("2.4+foobar", version_extract_base("2.4+foobar"))

    def test_with_bzr(self):
        self.assertEquals("2.4+", version_extract_base("2.4+bzr32"))
        self.assertEquals("2.4~", version_extract_base("2.4~bzr32"))

    def test_with_git(self):
        self.assertEquals("2.4+", version_extract_base("2.4+git20101010"))
        self.assertEquals("2.4~", version_extract_base("2.4~gitaabbccdd"))

    def test_with_svn(self):
        self.assertEquals("2.4+", version_extract_base("2.4+svn45"))
        self.assertEquals("2.4~", version_extract_base("2.4~svn45"))

    def test_with_dfsg(self):
        self.assertEquals("2.4+", version_extract_base("2.4+bzr32+dfsg1"))
        self.assertEquals("2.4~", version_extract_base("2.4~bzr32+dfsg.1"))
        self.assertEquals("2.4~", version_extract_base("2.4~bzr32.dfsg.1"))
        self.assertEquals("2.4~", version_extract_base("2.4~bzr32dfsg.1"))
        self.assertEquals("1.6~", version_extract_base("1.6~git20120320.dfsg.1"))


class DebVersionVariableTests(TestCase):

    def write_changelog(self, version):
        contents = textwrap.dedent("""
            package (%s) experimental; urgency=low

              * Initial release. (Closes: #XXXXXX)

             -- Jelmer Vernooij <jelmer@debian.org>  Thu, 19 May 2011 10:07:41 +0100
            """ % version)[1:]
        return changelog.Changelog(file=contents)

    def test_empty_changelog(self):
        var = DebVersionVariable.from_changelog(None, changelog.Changelog())
        self.assertRaises(SubstitutionUnavailable, var.get)

    def test_simple(self):
        var = DebVersionVariable.from_changelog(
            None, self.write_changelog("2.3-1"))
        self.assertEquals("2.3-1", var.get())

    def test_epoch(self):
        var = DebVersionVariable.from_changelog(
            None, self.write_changelog("4:2.3-1"))
        self.assertEquals("4:2.3-1", var.get())


class RecipeBranchTests(TestCaseWithTransport):

    def test_substitute_time(self):
        time = datetime.datetime.utcfromtimestamp(1)
        base_branch = BaseRecipeBranch("base_url", "1-{time}", 0.2)
        substitute_time(base_branch, time)
        self.assertEqual("1-197001010000", base_branch.deb_version)
        substitute_time(base_branch, time)
        self.assertEqual("1-197001010000", base_branch.deb_version)

    def test_substitute_date(self):
        time = datetime.datetime.utcfromtimestamp(1)
        base_branch = BaseRecipeBranch("base_url", "1-{date}", 0.2)
        substitute_time(base_branch, time)
        self.assertEqual("1-19700101", base_branch.deb_version)
        substitute_time(base_branch, time)
        self.assertEqual("1-19700101", base_branch.deb_version)

    def test_substitute_branch_vars(self):
        base_branch = BaseRecipeBranch("base_url", "1", 0.2)
        wt = self.make_branch_and_tree("br")
        revid = wt.commit("acommit")
        substitute_branch_vars(base_branch, None, wt.branch, revid)
        self.assertEqual("1", base_branch.deb_version)
        substitute_branch_vars(base_branch, None, wt.branch, revid)
        self.assertEqual("1", base_branch.deb_version)
        base_branch = BaseRecipeBranch("base_url", "{revno}", 0.2)
        substitute_branch_vars(base_branch, None, wt.branch, revid)
        self.assertEqual("1", base_branch.deb_version)
        base_branch = BaseRecipeBranch("base_url", "{revno}", 0.2)
        substitute_branch_vars(base_branch, "foo", wt.branch, revid)
        self.assertEqual("{revno}", base_branch.deb_version)
        substitute_branch_vars(base_branch, "foo", wt.branch, revid)
        self.assertEqual("{revno}", base_branch.deb_version)
        base_branch = BaseRecipeBranch("base_url", "{revno:foo}", 0.2)
        substitute_branch_vars(base_branch, "foo", wt.branch, revid)
        self.assertEqual("1", base_branch.deb_version)

    def test_substitute_branch_vars_debupstream(self):
        wt = self.make_branch_and_tree("br")
        revid1 = wt.commit("acommit")
        cl_contents = ("package (0.1-1) unstable; urgency=low\n  * foo\n"
                    " -- maint <maint@maint.org>  Tue, 04 Aug 2009 "
                    "10:03:10 +0100\n")
        self.build_tree_contents(
            [("br/debian/", ), ('br/debian/changelog', cl_contents)])
        wt.add(['debian', 'debian/changelog'])
        revid2 = wt.commit("with changelog")
        base_branch = BaseRecipeBranch("base_url", "{debupstream}", 0.4)
        # No changelog file, so no substitution
        substitute_branch_vars(base_branch, None, wt.branch, revid1)
        self.assertEqual("{debupstream}", base_branch.deb_version)
        substitute_branch_vars(base_branch, None, wt.branch, revid2)
        self.assertEqual("0.1", base_branch.deb_version)
        base_branch = BaseRecipeBranch("base_url", "{debupstream:tehname}", 0.4)
        substitute_branch_vars(base_branch, "tehname", wt.branch, revid2)
        self.assertEqual("0.1", base_branch.deb_version)

    def test_substitute_branch_vars_debupstream_pre_0_4(self):
        wt = self.make_branch_and_tree("br")
        cl_contents = ("package (0.1-1) unstable; urgency=low\n  * foo\n"
                    " -- maint <maint@maint.org>  Tue, 04 Aug 2009 "
                    "10:03:10 +0100\n")
        self.build_tree_contents(
            [("br/debian/", ), ('br/debian/changelog', cl_contents)])
        wt.add(['debian', 'debian/changelog'])
        revid = wt.commit("with changelog")
        # In recipe format < 0.4 {debupstream} gets replaced from the resulting
        # tree, not from the branch vars.
        base_branch = BaseRecipeBranch("base_url", "{debupstream}", 0.2)
        substitute_branch_vars(base_branch, None, wt.branch, revid)
        self.assertEqual("{debupstream}", base_branch.deb_version)
