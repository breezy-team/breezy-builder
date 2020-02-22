# bzr-builder: a bzr plugin to constuct trees based on recipes
# Copyright 2009-2010 Canonical Ltd.

# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3, as published
# by the Free Software Foundation.

# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranties of
# MERCHANTABILITY, SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR
# PURPOSE.  See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.

from base64 import standard_b64encode
import os
import shlex
import signal
import subprocess
import sys
from testtools.content import text_content
from textwrap import dedent

from breezy import (
    export as _mod_export,
    osutils,
    workingtree,
    )
from breezy.branch import Branch
from breezy.tests import (
    TestCaseWithTransport,
    )

from . import (
    Feature,
    PristineTarFeature,
    )

from debian import changelog


class _NotUnderFakeRootFeature(Feature):

    def _probe(self):
        return 'FAKEROOTKEY' not in os.environ

    def feature_name(self):
        return 'not running inside fakeroot'


NotUnderFakeRootFeature = _NotUnderFakeRootFeature()


def make_pristine_tar_delta(dest, tarball_path):
    """Create a pristine-tar delta for a tarball.

    :param dest: Directory to generate pristine tar delta for
    :param tarball_path: Path to the tarball
    :return: pristine-tarball
    """
    def subprocess_setup():
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    # If tarball_path is relative, the cwd=dest parameter to Popen will make
    # pristine-tar faaaail. pristine-tar doesn't use the VFS either, so we
    # assume local paths.
    tarball_path = osutils.abspath(tarball_path)
    command = ["pristine-tar", "gendelta", tarball_path, "-"]
    proc = subprocess.Popen(
        command, stdout=subprocess.PIPE,
        cwd=dest, preexec_fn=subprocess_setup,
        stderr=subprocess.PIPE)
    (stdout, stderr) = proc.communicate()
    if proc.returncode != 0:
        raise Exception("Generating delta from tar failed: %s" % stderr)
    return stdout


class BlackboxBuilderTests(TestCaseWithTransport):

    def _run(self, cmd, args, retcode):
        cmd = [sys.executable, "-m", "brzbuildrecipe." + cmd]
        if isinstance(args, str):
            cmd += shlex.split(args)
        else:
            cmd += list(args)
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
        stdout, stderr = process.communicate()
        if stdout:
            self.addDetail("stdout", text_content(stdout))
        if stderr:
            self.addDetail("stderr", text_content(stderr))
        self.assertEqual(retcode, process.returncode)
        return stdout, stderr

    def run_build(self, args, retcode=0):
        return self._run("build", args, retcode=retcode)

    def run_dailydeb(self, args, retcode=0):
        return self._run("dailydeb", args, retcode=retcode)

    def setUp(self):
        super(BlackboxBuilderTests, self).setUp()
        # Replace DEBEMAIL and DEBFULLNAME so that they are known values
        # for the changelog checks.
        self.overrideEnv("DEBEMAIL", "maint@maint.org")
        self.overrideEnv("DEBFULLNAME", "M. Maintainer")

    def _get_file_contents(self, filename, mode="r"):
        """Helper to read contents of a file

        Use check_file_content instead to just assert the contents match."""
        self.assertPathExists(filename)
        with open(filename, mode) as f:
            return f.read()

    def test_cmd_builder_exists(self):
        self.run_build("--help")

    def test_cmd_builder_requires_recipe_file_argument(self):
        err = self.run_build("", retcode=2)[1]
        if sys.version_info >= (3, 0):
            self.assertEqual(
                'usage: build.py [-h] [--manifest PATH] '
                '[--revision REVISION]\n'
                '                [--if-changed-from PATH]\n'
                '                LOCATION WORKING-BASEDIR\n'
                'build.py: error: the following arguments are '
                'required: LOCATION, WORKING-BASEDIR\n',
                err)
        else:
            self.assertEqual(
                'usage: build.py [-h] [--manifest PATH] '
                '[--revision REVISION]\n'
                '                [--if-changed-from PATH]\n'
                '                LOCATION WORKING-BASEDIR\n'
                'build.py: error: too few arguments\n',
                err)

    def test_cmd_builder_requires_working_dir_argument(self):
        err = self.run_build("recipe", retcode=2)[1]
        if sys.version_info >= (3, 0):
            self.assertEqual(
                'usage: build.py [-h] [--manifest PATH] '
                '[--revision REVISION]\n'
                '                [--if-changed-from PATH]\n'
                '                LOCATION WORKING-BASEDIR\n'
                'build.py: error: the following arguments are required: '
                'WORKING-BASEDIR\n',
                err)
        else:
            self.assertEqual(
                'usage: build.py [-h] [--manifest PATH] '
                '[--revision REVISION]\n'
                '                [--if-changed-from PATH]\n'
                '                LOCATION WORKING-BASEDIR\n'
                'build.py: error: too few arguments\n',
                err)

    def test_cmd_builder_nonexistant_recipe(self):
        err = self.run_build("recipe working", retcode=3)[1]
        self.assertEqual(
            "ERROR: Specified recipe does not exist: recipe\n", err)

    def test_cmd_builder_simple_recipe(self):
        self.build_tree_contents(
            [("recipe", b"# bzr-builder format 0.1 deb-version 1\nsource\n")])
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        source.add(["a"])
        revid = source.commit("one")
        self.run_build("recipe working")
        self.assertPathExists("working/a")
        tree = workingtree.WorkingTree.open("working")
        self.assertEqual(revid, tree.last_revision())
        self.assertPathExists("working/bzr-builder.manifest")
        self.check_file_contents(
            "working/bzr-builder.manifest",
            b"# bzr-builder format 0.1 deb-version 1\nsource revid:%s\n"
            % revid)

    def test_cmd_builder_simple_branch(self):
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        source.add(["a"])
        revid = source.commit("one")
        self.run_build("source working")
        self.assertPathExists("working/a")
        tree = workingtree.WorkingTree.open("working")
        self.assertEqual(revid, tree.last_revision())
        self.assertPathExists("working/bzr-builder.manifest")
        self.check_file_contents(
            "working/bzr-builder.manifest",
            b"# bzr-builder format 0.4\nsource revid:%s\n"
            % revid)

    def test_cmd_builder_simple_recipe_no_debversion(self):
        self.build_tree_contents(
            [("recipe", b"# bzr-builder format 0.1\nsource\n")])
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        source.add(["a"])
        revid = source.commit("one")
        self.run_build("recipe working")
        self.assertPathExists("working/a")
        tree = workingtree.WorkingTree.open("working")
        self.assertEqual(revid, tree.last_revision())
        self.assertPathExists("working/bzr-builder.manifest")
        self.check_file_contents(
            "working/bzr-builder.manifest",
            b"# bzr-builder format 0.1\nsource revid:%s\n"
            % revid)

    def test_cmd_builder_manifest(self):
        self.build_tree_contents(
            [("recipe", b"# bzr-builder format 0.1 deb-version 1\nsource\n")])
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        source.add(["a"])
        revid = source.commit("one")
        self.run_build("recipe working --manifest manifest")
        self.assertPathExists("working/a")
        self.assertPathExists("manifest")
        self.check_file_contents(
            "manifest", b"# bzr-builder format 0.1 "
            b"deb-version 1\nsource revid:%s\n" % revid)

    def test_cmd_builder_if_changed_does_not_exist(self):
        self.build_tree_contents(
            [("recipe", "# bzr-builder format 0.1 "
              "deb-version 1\nsource\n")])
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        source.add(["a"])
        source.commit("one")
        out, err = self.run_build("recipe working --if-changed-from manifest")

    def test_cmd_builder_if_changed_not_changed(self):
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        source.add(["a"])
        revid = source.commit("one")
        self.build_tree_contents(
            [("recipe", "# bzr-builder format 0.1 deb-version 1\nsource 1\n")])
        self.build_tree_contents(
            [("old-manifest", b"# bzr-builder format 0.1 "
              b"deb-version 1\nsource revid:%s\n" % revid)])
        out, err = self.run_build(
            "recipe working --manifest manifest "
            "--if-changed-from old-manifest")
        self.assertPathDoesNotExist("working")
        self.assertPathDoesNotExist("manifest")
        self.assertEqual("Unchanged\n", err)

    def test_cmd_builder_if_changed_changed(self):
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        source.add(["a"])
        revid = source.commit("one")
        self.build_tree_contents(
            [("recipe", "# bzr-builder format 0.1 "
                "deb-version 1\nsource 1\n")])
        self.build_tree_contents(
                [("old-manifest", "# bzr-builder format 0.1 "
                    "deb-version 1\nsource revid:foo\n")])
        out, err = self.run_build(
            "recipe working --manifest manifest "
            "--if-changed-from old-manifest")
        self.assertPathExists("working/a")
        self.assertPathExists("manifest")
        self.check_file_contents(
            "manifest", b"# bzr-builder format 0.1 "
            b"deb-version 1\nsource revid:%s\n" % revid)

    def test_cmd_dailydeb(self):
        self.requireFeature(NotUnderFakeRootFeature)
        # TODO: define a test feature for debuild and require it here.
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a", "source/debian/"])
        self.build_tree_contents(
            [("source/debian/rules", b"#!/usr/bin/make -f\nclean:\n"),
             ("source/debian/control",
                 b"Source: foo\nMaintainer: maint maint@maint.org\n\n"
                 b"Package: foo\nArchitecture: all\n")])
        source.add(["a", "debian/", "debian/rules", "debian/control"])
        revid = source.commit("one")
        self.build_tree_contents(
            [("test.recipe", "# bzr-builder format 0.1 "
              "deb-version 1\nsource 1\n")])
        out, err = self.run_dailydeb(
            "test.recipe working " "--manifest manifest")
        self.assertPathDoesNotExist("working/a")
        package_root = "working/test-1/"
        self.assertPathExists(os.path.join(package_root, "a"))
        self.assertPathExists(
            os.path.join(package_root, "debian/bzr-builder.manifest"))
        self.assertPathExists("manifest")
        self.check_file_contents(
            "manifest", b"# bzr-builder format 0.1 "
            b"deb-version 1\nsource revid:%s\n" % revid)
        self.check_file_contents(
            os.path.join(package_root, "debian/bzr-builder.manifest"),
            b"# bzr-builder format 0.1 deb-version 1\nsource revid:%s\n"
            % revid)
        cl_contents = self._get_file_contents(
            os.path.join(package_root, "debian/changelog"))
        self.assertEqual(
            "foo (1) lucid; urgency=low\n",
            cl_contents.splitlines(True)[0])

    def test_cmd_dailydeb_no_work_dir(self):
        self.requireFeature(NotUnderFakeRootFeature)
        # TODO: define a test feature for debuild and require it here.
        if getattr(self, "permit_dir", None) is not None:
            self.permit_dir('/')  # Allow the made working dir to be accessed.
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a", "source/debian/"])
        self.build_tree_contents(
            [("source/debian/rules", "#!/usr/bin/make -f\nclean:\n"),
             ("source/debian/control",
                 "Source: foo\nMaintainer: maint maint@maint.org\n\n"
                 "Package: foo\nArchitecture: all\n")])
        source.add(["a", "debian/", "debian/rules", "debian/control"])
        source.commit("one")
        self.build_tree_contents(
            [("test.recipe", "# bzr-builder format 0.1 "
              "deb-version 1\nsource 1\n")])
        out, err = self.run_dailydeb(
            "test.recipe --manifest manifest")

    def test_cmd_dailydeb_if_changed_from_non_existant(self):
        self.requireFeature(NotUnderFakeRootFeature)
        # TODO: define a test feature for debuild and require it here.
        if getattr(self, "permit_dir", None) is not None:
            self.permit_dir('/')  # Allow the made working dir to be accessed.
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a", "source/debian/"])
        self.build_tree_contents(
            [("source/debian/rules", "#!/usr/bin/make -f\nclean:\n"),
             ("source/debian/control",
                 "Source: foo\nMaintainer: maint maint@maint.org\n"
                 "\nPackage: foo\nArchitecture: all\n")])
        source.add(["a", "debian/", "debian/rules", "debian/control"])
        source.commit("one")
        self.build_tree_contents(
            [("test.recipe", "# bzr-builder format 0.1 "
              "deb-version 1\nsource 1\n")])
        out, err = self.run_dailydeb(
            "test.recipe --manifest manifest --if-changed-from bar")

    def make_upstream_version(
            self, version, contents, pristine_tar_format=None):
        upstream = self.make_branch_and_tree("upstream")
        self.build_tree_contents(contents)
        upstream.smart_add([upstream.basedir])
        revprops = {}
        if pristine_tar_format is not None:
            _mod_export.export(upstream, "export")
            if pristine_tar_format == "gz":
                tarfile_path = "export.tar.gz"
                _mod_export.export(upstream, tarfile_path, "tgz")
                revprops["deb-pristine-delta"] = standard_b64encode(
                    make_pristine_tar_delta(
                        "export", "export.tar.gz")).decode('ascii')
            elif pristine_tar_format == "bz2":
                tarfile_path = "export.tar.bz2"
                _mod_export.export(upstream, tarfile_path, "tbz2")
                revprops["deb-pristine-delta-bz2"] = standard_b64encode(
                    make_pristine_tar_delta(
                        "export", "export.tar.bz2")).decode('ascii')
            else:
                raise AssertionError(
                    "unknown pristine tar format %s" %
                    pristine_tar_format)
        else:
            tarfile_path = "export.tar.gz"
            _mod_export.export(upstream, tarfile_path, "tgz")
        tarfile_sha1 = osutils.sha_file_by_name(tarfile_path)
        revid = upstream.commit(
            "import upstream %s" % version,
            revprops=revprops)
        source = Branch.open("source")
        source.repository.fetch(upstream.branch.repository)
        source.tags.set_tag("upstream-%s" % version, revid)
        return tarfile_sha1

    def make_simple_package(self, path):
        source = self.make_branch_and_tree(path)
        self.build_tree(
            [os.path.join(path, "a"), os.path.join(path, "debian/")])
        cl_contents = (
            "package (0.1-1) unstable; urgency=low\n  * foo\n"
            " -- maint <maint@maint.org>  Tue, 04 Aug 2009 "
            "10:03:10 +0100\n")
        self.build_tree_contents([
            (os.path.join(path, "debian/rules"),
                "#!/usr/bin/make -f\nclean:\n"),
            (os.path.join(path, "debian/control"),
                "Source: package\nMaintainer: maint maint@maint.org\n\n"
                "Package: package\nArchitecture: all\n"),
            (os.path.join(path, "debian/changelog"),
                cl_contents)
            ])
        source.add(
            ["a", "debian/", "debian/rules", "debian/control",
             "debian/changelog"])
        source.commit("one")
        return source

    def test_cmd_dailydeb_no_build(self):
        self.make_simple_package("source")
        self.build_tree_contents(
            [("test.recipe", "# bzr-builder format 0.1 "
              "deb-version 1\nsource 1\n")])
        out, err = self.run_dailydeb(
                "--manifest manifest --no-build test.recipe working")
        new_cl_contents = (
            "package (1) unstable; urgency=low\n\n"
            "  * Auto build.\n\n -- M. Maintainer <maint@maint.org>  ")
        actual_cl_contents = self._get_file_contents(
            "working/package-1/debian/changelog")
        self.assertStartsWith(actual_cl_contents, new_cl_contents)
        for fn in os.listdir("working"):
            self.assertFalse(fn.endswith(".changes"))

    def test_cmd_dailydeb_with_package_from_changelog(self):
        # TODO: define a test feature for debuild and require it here.
        self.requireFeature(NotUnderFakeRootFeature)
        self.make_simple_package("source")
        self.build_tree_contents(
            [("test.recipe", "# bzr-builder format 0.1 "
              "deb-version 1\nsource 1\n")])
        out, err = self.run_dailydeb(
            "test.recipe working "
            "--manifest=manifest --if-changed-from=bar")
        new_cl_contents = (
            "package (1) unstable; urgency=low\n\n"
            "  * Auto build.\n\n -- M. Maintainer <maint@maint.org>  ")
        actual_cl_contents = self._get_file_contents(
            "working/test-1/debian/changelog")
        self.assertStartsWith(actual_cl_contents, new_cl_contents)

    def test_cmd_dailydeb_with_version_from_changelog(self):
        self.requireFeature(NotUnderFakeRootFeature)
        self.make_simple_package("source")
        self.build_tree_contents(
            [("test.recipe", "# bzr-builder format 0.3 "
              "deb-version {debversion}-2\nsource 1\n")])
        out, err = self.run_dailydeb(
            "test.recipe working --allow-fallback-to-native")
        cl = changelog.Changelog(
            self._get_file_contents(
                "working/test-{debversion}-2/debian/changelog"))
        self.assertEquals("0.1-1-2", str(cl._blocks[0].version))

    def test_cmd_dailydeb_with_version_from_other_branch_changelog(self):
        self.requireFeature(NotUnderFakeRootFeature)
        self.make_simple_package("source")
        other = self.make_simple_package("other")
        cl_contents = (
            "package (0.4-1) unstable; urgency=low\n  * foo\n"
            " -- maint <maint@maint.org>  Tue, 04 Aug 2009 "
            "10:03:10 +0100\n")
        self.build_tree_contents([
            (os.path.join("other", "debian", "changelog"), cl_contents)
            ])
        other.commit("new changelog entry")
        self.build_tree_contents(
            [("test.recipe", "# bzr-builder format 0.4 "
              "deb-version {debversion:other}.2\n"
              "source 1\n"
              "nest other other other\n")])
        out, err = self.run_dailydeb(
            "--allow-fallback-to-native test.recipe working")
        cl = changelog.Changelog(self._get_file_contents(
            "working/test-{debversion:other}.2/debian/changelog"))
        self.assertEquals("0.4-1.2", str(cl._blocks[0].version))

    def test_cmd_dailydeb_with_upstream_version_from_changelog(self):
        self.requireFeature(NotUnderFakeRootFeature)
        self.make_simple_package("source")
        self.build_tree_contents(
                [("test.recipe", "# bzr-builder format 0.1 "
                  "deb-version {debupstream}-2\nsource 1\n")])
        out, err = self.run_dailydeb(
            "--allow-fallback-to-native test.recipe working")
        new_cl_contents = (
            "package (0.1-2) unstable; urgency=low\n\n"
            "  * Auto build.\n\n -- M. Maintainer <maint@maint.org>  ")
        actual_cl_contents = self._get_file_contents(
            "working/test-{debupstream}-2/debian/changelog")
        self.assertStartsWith(actual_cl_contents, new_cl_contents)

    def test_cmd_dailydeb_with_append_version(self):
        self.requireFeature(NotUnderFakeRootFeature)
        self.make_simple_package("source")
        self.build_tree_contents(
            [("test.recipe", "# bzr-builder format 0.1 "
              "deb-version 1\nsource 1\n")])
        out, err = self.run_dailydeb(
            "test.recipe working --append-version ~ppa1")
        new_cl_contents = (
            "package (1~ppa1) unstable; urgency=low\n\n"
            "  * Auto build.\n\n -- M. Maintainer <maint@maint.org>  ")
        actual_cl_contents = self._get_file_contents(
            "working/test-1/debian/changelog")
        self.assertStartsWith(actual_cl_contents, new_cl_contents)

    def test_cmd_dailydeb_with_nonascii_maintainer_in_changelog(self):
        user_enc = osutils.get_user_encoding()
        name = u"Micha\u25c8 Sawicz"
        if sys.version_info >= (3, ):
            os.environ["DEBFULLNAME"] = name
        else:
            try:
                os.environ["DEBFULLNAME"] = name.encode(user_enc)
            except UnicodeEncodeError:
                self.skip(
                    "Need user encoding other than %r to test maintainer "
                    "name from environment" % (user_enc,))
        self.make_simple_package("source")
        self.build_tree_contents(
            [("test.recipe", "# bzr-builder format 0.1 "
              "deb-version 1\nsource 1\n")])
        out, err = self.run_dailydeb("test.recipe working")
        new_cl_contents = (
            u"package (1) unstable; urgency=low\n\n"
            u"  * Auto build.\n\n"
            u" -- Micha\u25c8 Sawicz <maint@maint.org>  ")
        actual_cl_contents = self._get_file_contents(
            "working/test-1/debian/changelog")
        self.assertStartsWith(actual_cl_contents, new_cl_contents)

    def test_cmd_dailydeb_with_invalid_version(self):
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        self.build_tree_contents([
            ("source/debian/", None),
            ("source/debian/control",
             "Source: foo\nMaintainer: maint maint@maint.org\n")
            ])
        source.add(["a", "debian", "debian/control"])
        source.commit("one")
        self.build_tree_contents(
            [("test.recipe", "# bzr-builder format 0.1 "
              "deb-version $\nsource 1\n"), ])
        err = self.run_dailydeb("test.recipe working", retcode=3)[1]
        self.assertContainsRe(
            err, "ERROR: Invalid deb-version: \\$: "
            "(Could not parse version: \\$|Invalid version string '\\$')\n")

    def test_cmd_dailydeb_with_safe(self):
        self.make_simple_package("source")
        self.build_tree_contents(
            [("test.recipe", "# bzr-builder format 0.3 "
                "deb-version 1\nsource 1\nrun something bad")])
        out, err = self.run_dailydeb(
            "test.recipe working --safe", retcode=3)
        self.assertContainsRe(err, "The 'run' instruction is forbidden.$")

    def make_simple_quilt_package(self):
        source = self.make_simple_package("source")
        self.build_tree(["source/debian/source/"])
        self.build_tree_contents([
            ("source/debian/source/format", "3.0 (quilt)\n"),
            ("source/debian/source/options", 'compression = "gzip"\n')])
        source.add([
            "debian/source", "debian/source/format", "debian/source/options"])
        source.commit("set source format")
        return source

    def test_cmd_dailydeb_missing_orig_tarball(self):
        self.make_simple_quilt_package()
        self.build_tree_contents(
            [("test.recipe", "# bzr-builder format 0.3 "
                "deb-version 1-1\nsource 1\n")])
        out, err = self.run_dailydeb(
            "test.recipe working",
            retcode=3)
        self.assertEquals("", out)
        self.assertEquals(
            'ERROR: Unable to find the upstream source. '
            'Import it as tag upstream-1 or build with '
            '--allow-fallback-to-native.\n', err)

    def test_cmd_dailydeb_with_orig_tarball(self):
        self.requireFeature(NotUnderFakeRootFeature)
        self.make_simple_package("source")
        self.make_upstream_version("0.1", [("upstream/file", "content\n")])
        self.build_tree_contents(
            [("test.recipe", "# bzr-builder format 0.3 "
                "deb-version 0.1-1\nsource\n")])
        out, err = self.run_dailydeb(
            "test.recipe working", retcode=0)
        self.assertPathExists("working/package_0.1.orig.tar.gz")
        self.assertPathExists("working/package_0.1-1.diff.gz")

    def test_cmd_dailydeb_with_pristine_orig_gz_tarball(self):
        self.requireFeature(NotUnderFakeRootFeature)
        self.requireFeature(PristineTarFeature)
        self.make_simple_package("source")
        pristine_tar_sha1 = self.make_upstream_version(
            "0.1", [("upstream/file", "content\n")], pristine_tar_format="gz")
        self.build_tree_contents(
            [("test.recipe", "# bzr-builder format 0.3 "
                "deb-version 0.1-1\nsource\n")])
        out, err = self.run_dailydeb(
            "test.recipe working", retcode=0)
        self.assertPathExists("working/package_0.1.orig.tar.gz")
        self.assertPathExists("working/package_0.1-1.diff.gz")
        self.assertEquals(
            osutils.sha_file_by_name("working/package_0.1.orig.tar.gz"),
            pristine_tar_sha1)

    def test_cmd_dailydeb_with_pristine_orig_bz2_tarball(self):
        self.requireFeature(NotUnderFakeRootFeature)
        self.requireFeature(PristineTarFeature)
        self.make_simple_quilt_package()
        pristine_tar_sha1 = self.make_upstream_version("0.1", [
            ("upstream/file", "content\n"),
            ("upstream/a", "contents of source/a\n")],
            pristine_tar_format="bz2")
        self.build_tree_contents(
            [("test.recipe", b"# bzr-builder format 0.3 "
              b"deb-version 0.1-1\nsource\n")])
        wt = workingtree.WorkingTree.open("source")
        self.build_tree([("source/upstream/")])
        self.build_tree_contents([
            ("source/upstream/file", "content\n"),
            ("source/upstream/a", "contents of source/a\n")])
        wt.add(["upstream", "upstream/file", "upstream/a"])
        out, err = self.run_dailydeb(
            "test.recipe working", retcode=0)
        self.assertPathExists("working/package_0.1.orig.tar.bz2")
        self.assertPathExists("working/package_0.1-1.debian.tar.gz")
        self.assertEquals(
            osutils.sha_file_by_name("working/package_0.1.orig.tar.bz2"),
            pristine_tar_sha1)

    def test_cmd_dailydeb_allow_fallback_to_native_with_orig_tarball(self):
        self.requireFeature(PristineTarFeature)
        self.make_simple_quilt_package()
        pristine_tar_sha1 = self.make_upstream_version("0.1", [
            ("upstream/file", "content\n"),
            ("upstream/a", "contents of source/a\n")],
            pristine_tar_format="bz2")
        self.build_tree_contents(
            [("test.recipe", b"# bzr-builder format 0.3 "
              b"deb-version 0.1-1\nsource\n")])
        wt = workingtree.WorkingTree.open("source")
        self.build_tree([("source/upstream/")])
        self.build_tree_contents([
            ("source/upstream/file", "content\n"),
            ("source/upstream/a", "contents of source/a\n")])
        wt.add(["upstream", "upstream/file", "upstream/a"])
        out, err = self.run_dailydeb(
            "--allow-fallback-to-native test.recipe working",
            retcode=0)
        self.assertPathExists("working/package_0.1.orig.tar.bz2")
        self.assertPathExists("working/package_0.1-1.debian.tar.gz")
        with open("source/debian/source/format", "r") as f:
            self.assertEquals("3.0 (quilt)\n", f.read())
        self.assertEquals(
            osutils.sha_file_by_name("working/package_0.1.orig.tar.bz2"),
            pristine_tar_sha1)

    def test_cmd_dailydeb_force_native(self):
        self.requireFeature(NotUnderFakeRootFeature)
        self.make_simple_quilt_package()
        self.build_tree_contents(
            [("test.recipe", "# bzr-builder format 0.3 "
                "deb-version 1\nsource 2\n")])
        out, err = self.run_dailydeb(
            "--allow-fallback-to-native test.recipe working",
            retcode=0)
        self.assertFileEqual(
            "3.0 (native)\n", "working/test-1/debian/source/format")

    def test_cmd_dailydeb_force_native_empty_series(self):
        self.requireFeature(NotUnderFakeRootFeature)
        source = self.make_simple_quilt_package()
        self.build_tree(['source/debian/patches/'])
        self.build_tree_contents([
            ("test.recipe", "# bzr-builder format 0.3 "
             "deb-version 1\nsource 3\n"),
            ("source/debian/patches/series", "\n")])
        source.add(["debian/patches", "debian/patches/series"])
        source.commit("add patches")
        out, err = self.run_dailydeb(
            "--allow-fallback-to-native test.recipe working",
            retcode=0)
        self.assertFileEqual(
            "3.0 (native)\n",
            "working/test-1/debian/source/format")
        self.assertPathDoesNotExist("working/test-1/debian/patches")

    def test_cmd_dailydeb_force_native_apply_quilt(self):
        self.requireFeature(NotUnderFakeRootFeature)
        source = self.make_simple_quilt_package()
        self.build_tree(["source/debian/patches/"])
        patch = dedent("""\
           diff -ur a/thefile b/thefile
           --- a/thefile	2010-12-05 20:14:22.000000000 +0100
           +++ b/thefile	2010-12-05 20:14:26.000000000 +0100
           @@ -1 +1 @@
           -old-contents
           +new-contents
           """)
        self.build_tree_contents([
            ("source/thefile", "old-contents\n"),
            ("source/debian/patches/series", "01_foo.patch"),
            ("source/debian/patches/01_foo.patch", patch)])
        source.add(["thefile", "debian/patches", "debian/patches/series",
                    "debian/patches/01_foo.patch"])
        source.commit("add patch")

        self.build_tree_contents(
            [("test.recipe", "# bzr-builder format 0.3 "
                "deb-version 1\nsource\n")])
        out, err = self.run_dailydeb(
            "--allow-fallback-to-native test.recipe working",
            retcode=0)
        self.assertFileEqual(
            "3.0 (native)\n",
            "working/test-1/debian/source/format")
        self.assertFileEqual(
            "new-contents\n",
            "working/test-1/thefile")
        self.assertPathDoesNotExist("working/test-1/debian/patches")

    def test_cmd_dailydeb_force_native_apply_quilt_failure(self):
        source = self.make_simple_quilt_package()
        self.build_tree(["source/debian/patches/"])
        patch = dedent("""\
           diff -ur a/thefile b/thefile
           --- a/thefile	2010-12-05 20:14:22.000000000 +0100
           +++ b/thefile	2010-12-05 20:14:26.000000000 +0100
           @@ -1 +1 @@
           -old-contents
           +new-contents
           """)
        self.build_tree_contents([
            ("source/thefile", "contents\n"),
            ("source/debian/patches/series", "01_foo.patch"),
            ("source/debian/patches/01_foo.patch", patch)])
        source.add(["thefile", "debian/patches", "debian/patches/series",
                    "debian/patches/01_foo.patch"])
        source.commit("add patch")

        self.build_tree_contents(
            [("test.recipe", "# bzr-builder format 0.3 "
                "deb-version 1-1\nsource 3\n")])
        out, err = self.run_dailydeb(
            "--allow-fallback-to-native test.recipe working",
            retcode=3)
        self.assertContainsRe(err, "ERROR: Failed to apply quilt patches")

    def test_unknown_source_format(self):
        source = self.make_simple_package("source")
        self.build_tree(["source/debian/source/"])
        self.build_tree_contents([
            ("source/debian/source/format", "2.0\n")])
        source.add(["debian/source", "debian/source/format"])
        source.commit("set source format")

        self.build_tree_contents(
            [("test.recipe", "# bzr-builder format 0.3 "
              "deb-version 1-1\nsource\n")])
        out, err = self.run_dailydeb(
            "--allow-fallback-to-native test.recipe working", retcode=3)
        self.assertEquals(err, "ERROR: Unknown source format 2.0\n")
