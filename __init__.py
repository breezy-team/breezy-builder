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

"""The bzr-builder plugin allows you to construct a branch from a 'recipe'.

The recipe is a series of pointers to branches and instructions for how they
should be combined. There are two ways to combine branches, by merging, and
by nesting, allowing much flexibility.

A recipe is just a text file that starts with a line such as

# bzr-builder format 0.3 deb-version 1.0+{revno}-{revno:packaging}

The format specifier is there to allow the syntax to be changed in later
versions, and the meaning of "deb-version" will be explained later.

The next step is the define the base branch, this is the branch that will
be places at the root, e.g. just put

lp:foo

to use the trunk of "foo" hosted on LaunchPad.

Next comes any number of lines of other branches to be merged in, but using
a slightly different format. To merge a branch in to the base specify
something like

merge packaging lp:~foo-dev/foo/packaging

which specifies we are merging a branch we will refer to as "packaging", which
can be found at the given URI. The name you give to the branch as the second
item doesn't have to match anything else, it's just an identifier specific
to the recipe.

If you wish to nest a branch then you use a similar line

nest artwork lp:foo-images images

This specifies that we are nesting the branch at lp:foo-images, which we will
call "artwork", and we will place it locally in to the "images" directory.

You can then continue in this fashion for as many branches as you like. It
is also possible to nest and merge branches in to nested branches. For example
to merge a branch in to the "artwork" branch we put the following on the line
below that one, indented by two spaces.

  merge artwork-fixes lp:~bob/foo-images/fix-12345

which will merge Bob's fixes branch in to the "artwork" branch which we nested
at "images".

It is also possible to specify particular revisions of a branch by appending
a revisionspec to the line. For instance

nest docs lp:foo-docs doc tag:1.0

will nest the revision pointed to by the "1.0" tag of that branch. The format
for the revisionspec is indentical to that taken by the "--revision" argument
to many bzr commands, see "bzr help revisionspec".

You can also merge specific subdirectories from a branch with a "nest-part"
line like

nest-part packaging lp:~foo-dev/foo/packaging -1 debian

which specifies that the only the debian/ subdirectory from revision -1 (i.e.
the latest revision) should be merged.  This works even if the branches share
no revision history.  You can optionally specify the subdirectory in the target
with a line like

nest-part libfoo lp:libfoo -1 src lib/foo

will put the "src" directory of libfoo in "lib/foo".

It is also possible to run an arbitrary command at a particular point in the
construction process.

run autoreconf -i

will run autotools at a particular point. Doing things with branches is usually
preferred, but sometimes it is the easier or only way to achieve something.
Note that you usually shouldn't rely on having general Internet access when
assembling the recipe, so commands that would require it should be avoided.

You can then build this branch by running

bzr build foo.recipe working-dir

(assuming you saved it as foo.recipe in your current directory).

Once the command finished it will have placed the result in "working-dir".

It is also possible to produce Debian source packages from a recipe, assuming
that one of the branches in the recipe contains some appropriate packaging.
You can do this using the "bzr dailydeb" command, which takes the same
arguments as "build". Only this time im working dir you will find a source
package and a directory containing the code that the packages was built from
once it is done. Also take a look at the "--key-id" and "--dput" arguments
to have "bzr dailydeb" sign and upload the source package somewhere.

To build Debian source package that you desire you should make sure that
"deb-version" is set to an appropriate value on the first line of your
recipe. This will be used as the version number of the package. The
value you put there also allows for substution of values in to it based
on various things when the recipe is processed:

  * {time} will be substituted with the current date and time, such as
    200908191512.
  * {revno} will be the revno of the base branch (the first specified).
  * {revno:<branch name>} will be substituted with the revno for the
    branch named <branch name> in the recipe.

Instruction syntax summary:

  * nest NAME BRANCH TARGET-DIR [REVISION]
  * merge NAME BRANCH [REVISION]
  * nest-part NAME BRANCH REVISION SUBDIR [TARGET-DIR]
  * run COMMAND

Format versions:

  0.1 - original format.
  0.2 - added "run" instruction.
  0.3 - added "nest-part" instruction.
"""

if __name__ == '__main__':
    import os
    import subprocess
    import sys
    dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugins")
    retcode = subprocess.call("bzr selftest -s bzrlib.plugins.builder",
            shell=True, env={"BZR_PLUGIN_PATH": dir})
    sys.exit(retcode)

import datetime
from email import utils
import os
import pwd
import re
import socket
import shutil
import subprocess
import tempfile

from debian_bundle import changelog

from bzrlib import (
        errors,
        trace,
        transport,
        )
from bzrlib.commands import Command, register_command
from bzrlib.option import Option

from bzrlib.plugins.builder.recipe import (
        build_manifest,
        build_tree,
        RecipeParser,
        resolve_revisions,
        )


def write_manifest_to_path(path, base_branch):
    parent_dir = os.path.dirname(path)
    if parent_dir != '' and not os.path.exists(parent_dir):
        os.makedirs(parent_dir)
    manifest_f = open(path, 'wb')
    try:
        manifest_f.write(build_manifest(base_branch))
    finally:
        manifest_f.close()


def get_branch_from_recipe_file(recipe_file):
    recipe_transport = transport.get_transport(os.path.dirname(recipe_file))
    try:
        recipe_contents = recipe_transport.get_bytes(
                os.path.basename(recipe_file))
    except errors.NoSuchFile:
        raise errors.BzrCommandError("Specified recipe does not exist: "
                "%s" % recipe_file)
    parser = RecipeParser(recipe_contents, filename=recipe_file)
    return parser.parse()


def get_old_recipe(if_changed_from):
    old_manifest_transport = transport.get_transport(os.path.dirname(
                if_changed_from))
    try:
        old_manifest_contents = old_manifest_transport.get_bytes(
                os.path.basename(if_changed_from))
    except errors.NoSuchFile:
        return None
    old_recipe = RecipeParser(old_manifest_contents,
            filename=if_changed_from).parse()
    return old_recipe


def get_maintainer():
    """
    Create maintainer string using the same algorithm as in dch
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
        except KeyError, AttributeError:
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


def add_changelog_entry(base_branch, basedir, distribution=None,
        package=None):
    debian_dir = os.path.join(basedir, "debian")
    if not os.path.exists(debian_dir):
        os.makedirs(debian_dir)
    cl_path = os.path.join(debian_dir, "changelog")
    if os.path.exists(cl_path):
        cl_f = open(cl_path)
        try:
            cl = changelog.Changelog(file=cl_f)
        finally:
            cl_f.close()
    else:
        cl = changelog.Changelog()
    if len(cl._blocks) > 0:
        if distribution is None:
            distribution = cl._blocks[0].distributions.split()[0]
        if package is None:
            package = cl._blocks[0].package
        if "{debupstream}" in base_branch.deb_version:
            cl_version = cl._blocks[0].version
            base_branch.deb_version = base_branch.deb_version.replace(
                "{debupstream}", cl_version.upstream_version)
    else:
        if package is None:
            raise errors.BzrCommandError("No previous changelog to "
                    "take the package name from, and --package not "
                    "specified.")
        if "{debupstream}" in base_branch.deb_version:
            raise errors.BzrCommandError("No previous changelog to "
                    "take the upstream version from - {debupstream} was "
                    "used.")
        if distribution is None:
            distribution = "jaunty"
    # Use debian packaging environment variables
    # or default values if they don't exist
    author = "%s <%s>" % get_maintainer()

    date = utils.formatdate(localtime=True)
    cl.new_block(package=package, version=base_branch.deb_version,
            distributions=distribution, urgency="low",
            changes=['', '  * Auto build.', ''],
            author=author, date=date)
    cl_f = open(cl_path, 'wb')
    try:
        cl.write_to_open_file(cl_f)
    finally:
        cl_f.close()


def build_source_package(basedir):
    trace.note("Building the source package")
    command = ["/usr/bin/debuild", "--no-tgz-check", "-i", "-I", "-S",
                    "-uc", "-us"]
    proc = subprocess.Popen(command, cwd=basedir,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE)
    proc.stdin.close()
    retcode = proc.wait()
    if retcode != 0:
        output = proc.stdout.read()
        raise errors.BzrCommandError("Failed to build the source package: "
                "%s" % output)


def sign_source_package(basedir, key_id):
    trace.note("Signing the source package")
    command = ["/usr/bin/debsign", "-S", "-k%s" % key_id]
    proc = subprocess.Popen(command, cwd=basedir,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE)
    proc.stdin.close()
    retcode = proc.wait()
    if retcode != 0:
        output = proc.stdout.read()
        raise errors.BzrCommandError("Signing the package failed: "
                "%s" % output)


def dput_source_package(basedir, target):
    trace.note("Uploading the source package")
    command = ["/usr/bin/debrelease", "-S", "--dput", target]
    proc = subprocess.Popen(command, cwd=basedir,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE)
    proc.stdin.close()
    retcode = proc.wait()
    if retcode != 0:
        output = proc.stdout.read()
        raise errors.BzrCommandError("Uploading the package failed: "
                "%s" % output)


class cmd_build(Command):
    """Build a tree based on a 'recipe'.

    Pass the name of the recipe file and the directory to work in.

    See "bzr help builder" for more information on what a recipe is.
    """
    takes_args = ["recipe_file", "working_directory"]
    takes_options = [
            Option('manifest', type=str, argname="path",
                   help="Path to write the manifest to."),
            Option('if-changed-from', type=str, argname="path",
                   help="Only build if the outcome would be different "
                        "to that specified in the specified manifest."),
                    ]

    def _substitute_stuff(self, recipe_file, if_changed_from):
        """Common code to substitute stuff
        
        :return: A tuple with (retcode, base_branch). If retcode is None
            then the command execution should continue.
        """
        base_branch = get_branch_from_recipe_file(recipe_file)
        time = datetime.datetime.utcnow()
        base_branch.substitute_time(time)
        old_recipe = None
        if if_changed_from is not None:
            old_recipe = get_old_recipe(if_changed_from)
        # Save the unsubstituted version for dailydeb.
        self._template_version = base_branch.deb_version
        changed = resolve_revisions(base_branch, if_changed_from=old_recipe)
        if not changed:
            trace.note("Unchanged")
            return 0, base_branch
        return None, base_branch

    def run(self, recipe_file, working_directory, manifest=None,
            if_changed_from=None):
        result, base_branch = self._substitute_stuff(recipe_file,
            if_changed_from)
        if result is not None:
            return result
        manifest_path = manifest or os.path.join(working_directory,
                        "bzr-builder.manifest")
        build_tree(base_branch, working_directory)
        write_manifest_to_path(manifest_path, base_branch)


register_command(cmd_build)


class cmd_dailydeb(cmd_build):
    """Build a deb based on a 'recipe'.

    See "bzr help builder" for more information on what a recipe is.

    If you do not specify a working directory then a temporary
    directory will be used and it will be removed when the command
    finishes.
    """

    takes_options = cmd_build.takes_options + [
                Option("package", type=str,
                       help="The package name to use in the changelog entry. "
                            "If not specified then the package from the "
                            "previous changelog entry will be used, so it "
                            "must be specified if there is no changelog."),
                Option("distribution", type=str,
                        help="The distribution to target. If not specified "
                             "then the same distribution as the last entry "
                             "in debian/changelog will be used."),
                Option("dput", type=str, argname="target",
                        help="dput the built package to the specified "
                        "dput target."),
                Option("key-id", type=str, short_name="k",
                       help="Sign the packages with the specified GnuPG key, "
                            "must be specified if you use --dput."),
            ]

    takes_args = ["recipe_file", "working_basedir?"]

    def run(self, recipe_file, working_basedir=None, manifest=None,
            if_changed_from=None, package=None, distribution=None,
            dput=None, key_id=None):

        if dput is not None and key_id is None:
            raise errors.BzrCommandError("You must specify --key-id if you "
                    "specify --dput.")
        result, base_branch = self._substitute_stuff(recipe_file,
            if_changed_from)
        if result is not None:
            return result
        if working_basedir is None:
            temp_dir = tempfile.mkdtemp(prefix="bzr-builder-")
            working_basedir = temp_dir
        else:
            temp_dir = None
            if not os.path.exists(working_basedir):
                os.makedirs(working_basedir)
        self._calculate_package_name(recipe_file, package)
        working_directory = os.path.join(working_basedir,
            "%s-%s" % (self._package_name, self._template_version))
        try:
            # we want to use a consistent package_dir always to support
            # updates in place, but debuild etc want PACKAGE-UPSTREAMVERSION
            # on disk, so we build_tree with the unsubstituted version number
            # and do a final rename-to step before calling into debian build
            # tools. We then rename the working dir back.
            manifest_path = os.path.join(working_directory, "debian",
                "bzr-builder.manifest")
            build_tree(base_branch, working_directory)
            write_manifest_to_path(manifest_path, base_branch)
            # Add changelog also substitutes {debupstream}.
            add_changelog_entry(base_branch, working_directory,
                distribution=distribution, package=package)
            package_dir = self._calculate_package_dir(base_branch,
                working_basedir)
            # working_directory -> package_dir: after this debian stuff works.
            os.rename(working_directory, package_dir)
            try:
                build_source_package(package_dir)
                if key_id is not None:
                    sign_source_package(package_dir, key_id)
                if dput is not None:
                    dput_source_package(package_dir, dput)
            finally:
                # package_dir -> working_directory
                os.rename(package_dir, working_directory)
            # Note that this may write a second manifest.
            if manifest is not None:
                write_manifest_to_path(manifest, base_branch)
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir)

    def _calculate_package_dir(self, base_branch, working_basedir):
        """Calculate the directory name that should be used while debuilding."""
        version = base_branch.deb_version
        if "-" in version:
            version = version[:version.rindex("-")]
        package_basedir = "%s-%s" % (self._package_name, version)
        package_dir = os.path.join(working_basedir, package_basedir)
        return package_dir

    def _calculate_package_name(self, recipe_file, package):
        """Calculate the directory name that should be used while debuilding."""
        recipe_name = os.path.basename(recipe_file)
        if recipe_name.endswith(".recipe"):
            recipe_name = recipe_name[:-len(".recipe")]
        self._package_name = package or recipe_name


register_command(cmd_dailydeb)


def test_suite():
    from unittest import TestSuite
    from bzrlib.plugins.builder import tests
    result = TestSuite()
    result.addTest(tests.test_suite())
    return result
