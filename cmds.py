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

"""Subcommands provided by bzr-builder."""

import datetime
from email import utils
import errno
import os
import pwd
import re
import socket
import shutil
import subprocess
import tempfile

try:
    from debian import changelog
except ImportError:
    # In older versions of python-debian the main package was named 
    # debian_bundle
    from debian_bundle import changelog

from bzrlib import (
        errors,
        trace,
        transport,
        )
from bzrlib.commands import Command
from bzrlib.option import Option

from bzrlib.plugins.builder.recipe import (
        build_tree,
        DEBUPSTREAM_VAR,
        RecipeParser,
        resolve_revisions,
        SAFE_INSTRUCTIONS,
        )


# The default distribution used by add_changelog_entry()
DEFAULT_UBUNTU_DISTRIBUTION = "lucid"


class MissingDependency(errors.BzrError):
    pass


def write_manifest_to_path(path, base_branch):
    parent_dir = os.path.dirname(path)
    if parent_dir != '' and not os.path.exists(parent_dir):
        os.makedirs(parent_dir)
    manifest_f = open(path, 'wb')
    try:
        manifest_f.write(str(base_branch))
    finally:
        manifest_f.close()


def get_branch_from_recipe_file(recipe_file, safe=False):
    """Return the base branch for the specified recipe.

    :param recipe_file: The URL of the recipe file to retrieve.
    :param safe: if True, reject recipes that would cause arbitrary code
        execution.
    """
    recipe_transport = transport.get_transport(os.path.dirname(recipe_file))
    try:
        recipe_contents = recipe_transport.get_bytes(
                os.path.basename(recipe_file))
    except errors.NoSuchFile:
        raise errors.BzrCommandError("Specified recipe does not exist: "
                "%s" % recipe_file)
    if safe:
        permitted_instructions = SAFE_INSTRUCTIONS
    else:
        permitted_instructions = None
    parser = RecipeParser(recipe_contents, filename=recipe_file)
    return parser.parse(permitted_instructions=permitted_instructions)


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
    """Create maintainer string using the same algorithm as in dch.
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


def add_changelog_entry(base_branch, basedir, distribution=None,
        package=None, author_name=None, author_email=None,
        append_version=None):
    debian_dir = os.path.join(basedir, "debian")
    if not os.path.exists(debian_dir):
        os.makedirs(debian_dir)
    cl_path = os.path.join(debian_dir, "changelog")
    file_found = False
    if os.path.exists(cl_path):
        file_found = True
        cl_f = open(cl_path)
        try:
            contents = cl_f.read()
        finally:
            cl_f.close()
        cl = changelog.Changelog(file=contents)
    else:
        cl = changelog.Changelog()
    if len(cl._blocks) > 0:
        if distribution is None:
            distribution = cl._blocks[0].distributions.split()[0]
        if package is None:
            package = cl._blocks[0].package
        if DEBUPSTREAM_VAR in base_branch.deb_version:
            cl_version = cl._blocks[0].version
            base_branch.substitute_debupstream(cl_version)
    else:
        if file_found:
            if len(contents.strip()) > 0:
                reason = ("debian/changelog didn't contain any "
                         "parseable stanzas")
            else:
                reason = "debian/changelog was empty"
        else:
            reason = "debian/changelog was not present"
        if package is None:
            raise errors.BzrCommandError("No previous changelog to "
                    "take the package name from, and --package not "
                    "specified: %s." % reason)
        if DEBUPSTREAM_VAR in base_branch.deb_version:
            raise errors.BzrCommandError("No previous changelog to "
                    "take the upstream version from as %s was "
                    "used: %s." % (DEBUPSTREAM_VAR, reason))
        if distribution is None:
            distribution = DEFAULT_UBUNTU_DISTRIBUTION
    # Use debian packaging environment variables
    # or default values if they don't exist
    if author_name is None or author_email is None:
        author_name, author_email = get_maintainer()
    author = "%s <%s>" % (author_name, author_email)

    date = utils.formatdate(localtime=True)
    version = base_branch.deb_version
    if append_version is not None:
        version += append_version
    try:
        changelog.Version(version)
    except (changelog.VersionError, ValueError), e:
        raise errors.BzrCommandError("Invalid deb-version: %s: %s"
                % (version, e))
    cl.new_block(package=package, version=version,
            distributions=distribution, urgency="low",
            changes=['', '  * Auto build.', ''],
            author=author, date=date)
    cl_f = open(cl_path, 'wb')
    try:
        cl.write_to_open_file(cl_f)
    finally:
        cl_f.close()


def calculate_package_dir(base_branch, package_name, working_basedir):
    """Calculate the directory name that should be used while debuilding."""
    version = base_branch.deb_version
    if "-" in version:
        version = version[:version.rindex("-")]
    package_basedir = "%s-%s" % (package_name, version)
    package_dir = os.path.join(working_basedir, package_basedir)
    return package_dir


def _run_command(command, basedir, msg, error_msg,
        not_installed_msg=None, env=None, success_exit_codes=None):
    """ Run a command in a subprocess.

    :param command: list with command and parameters
    :param msg: message to display to the user
    :param error_msg: message to display if something fails.
    :param not_installed_msg: the message to display if the command
        isn't available.
    :param env: Optional environment to use rather than os.environ.
    :param success_exit_codes: Exit codes to consider succesfull, defaults to [0].
    """
    trace.note(msg)
    # Hide output if -q is in use.
    quiet = trace.is_quiet()
    if quiet:
        kwargs = {"stderr": subprocess.STDOUT, "stdout": subprocess.PIPE}
    else:
        kwargs = {}
    if env is not None:
        kwargs["env"] = env
    try:
        proc = subprocess.Popen(command, cwd=basedir,
                stdin=subprocess.PIPE, **kwargs)
    except OSError, e:
        if e.errno != errno.ENOENT:
            raise
        if not_installed_msg is None:
            raise
        raise MissingDependency(msg=not_installed_msg)
    output = proc.communicate()
    if success_exit_codes is None:
        success_exit_codes = [0]
    if proc.returncode not in success_exit_codes:
        if quiet:
            raise errors.BzrCommandError("%s: %s" % (error_msg, output))
        else:
            raise errors.BzrCommandError(error_msg)


def build_source_package(basedir):
    command = ["/usr/bin/debuild", "--no-tgz-check", "-i", "-I", "-S",
                    "-uc", "-us"]
    _run_command(command, basedir,
        "Building the source package",
        "Failed to build the source package",
        not_installed_msg="debuild is not installed, please install "
            "the devscripts package.")

def get_source_format(path):
    """Retrieve the source format name from a package.

    :param path: Path to the package
    :return: String with package format
    """
    source_format_path = os.path.join(path, "debian", "source", "format")
    if not os.path.exists(source_format_path):
        return "1.0"
    f = open(source_format_path, 'r')
    try:
        return f.read().strip()
    finally:
        f.close()


def convert_3_0_quilt_to_native(path):
    """Convert a package in 3.0 (quilt) format to 3.0 (native).

    This applies all patches in the package and updates the 
    debian/source/format file.

    :param path: Path to the package on disk
    """
    path = os.path.abspath(path)
    patches_dir = os.path.join(path, "debian", "patches")
    series_file = os.path.join(patches_dir, "series")
    if os.path.exists(series_file):
        _run_command(["quilt", "push", "-a", "-v"], path,
            "Applying quilt patches",
            "Failed to apply quilt patches",
            not_installed_msg="quilt is not installed, please install it.",
            env={"QUILT_SERIES": series_file, "QUILT_PATCHES": patches_dir},
            success_exit_codes=(0, 2))
    if os.path.exists(patches_dir):
        shutil.rmtree(patches_dir)
    f = open(os.path.join(path, "debian", "source", "format"), 'w')
    try:
        f.write("3.0 (native)\n")
    finally:
        f.close()


def force_native_format(working_tree_path):
    """Make sure a package is a format that supports native packages.

    :param working_tree_path: Path to the package
    """
    current_format = get_source_format(working_tree_path)
    if current_format == "3.0 (quilt)":
        convert_3_0_quilt_to_native(working_tree_path)
    elif current_format not in ("1.0", "3.0 (native)"):
        raise errors.BzrCommandError("Unknown source format %s" %
                                     current_format)


def sign_source_package(basedir, key_id):
    command = ["/usr/bin/debsign", "-S", "-k%s" % key_id]
    _run_command(command, basedir,
        "Signing the source package",
        "Signing the package failed",
        not_installed_msg="debsign is not installed, please install "
            "the devscripts package.")


def dput_source_package(basedir, target):
    command = ["/usr/bin/debrelease", "-S", "--dput", target]
    _run_command(command, basedir,
        "Uploading the source package",
        "Uploading the package failed",
        not_installed_msg="debrelease is not installed, please "
            "install the devscripts package.")


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

    def _get_prepared_branch_from_recipe(self, recipe_file,
            if_changed_from=None, safe=False):
        """Common code to prepare a branch and do substitutions.

        :param recipe_file: a path to a recipe file to work from.
        :param if_changed_from: an optional path to a manifest to
            compare the recipe against.
        :param safe: if True, reject recipes that would cause arbitrary code
            execution.
        :return: A tuple with (retcode, base_branch). If retcode is None
            then the command execution should continue.
        """
        base_branch = get_branch_from_recipe_file(recipe_file, safe=safe)
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
        result, base_branch = self._get_prepared_branch_from_recipe(recipe_file,
            if_changed_from=if_changed_from)
        if result is not None:
            return result
        manifest_path = manifest or os.path.join(working_directory,
                        "bzr-builder.manifest")
        build_tree(base_branch, working_directory)
        write_manifest_to_path(manifest_path, base_branch)


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
                       help="Sign the packages with the specified GnuPG key. "
                            "Must be specified if you use --dput."),
                Option("no-build",
                       help="Just ready the source package and don't "
                            "actually build it."),
                Option("watch-ppa", help="Watch the PPA the package was "
                    "dput to and exit with 0 only if it builds and "
                    "publishes successfully."),
                Option("append-version", type=str, help="Append the "
                        "specified string to the end of the version used "
                        "in debian/changelog."),
                Option("safe", help="Error if the recipe would cause"
                       " arbitrary code execution."),
            ]

    takes_args = ["recipe_file", "working_basedir?"]

    def run(self, recipe_file, working_basedir=None, manifest=None,
            if_changed_from=None, package=None, distribution=None,
            dput=None, key_id=None, no_build=None, watch_ppa=False,
            append_version=None, safe=False):

        if dput is not None and key_id is None:
            raise errors.BzrCommandError("You must specify --key-id if you "
                    "specify --dput.")
        if watch_ppa:
            if not dput:
                raise errors.BzrCommandError(
                    "cannot watch a ppa without doing dput.")
            else:
                # Check we can calculate a PPA url.
                target_from_dput(dput)

        result, base_branch = self._get_prepared_branch_from_recipe(recipe_file,
            if_changed_from=if_changed_from, safe=safe)
        if result is not None:
            return result
        if working_basedir is None:
            temp_dir = tempfile.mkdtemp(prefix="bzr-builder-")
            working_basedir = temp_dir
        else:
            temp_dir = None
            if not os.path.exists(working_basedir):
                os.makedirs(working_basedir)
        package_name = self._calculate_package_name(recipe_file, package)
        working_directory = os.path.join(working_basedir,
            "%s-%s" % (package_name, self._template_version))
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
                distribution=distribution, package=package,
                append_version=append_version)
            force_native_format(working_directory)
            package_dir = calculate_package_dir(base_branch,
                    package_name, working_basedir)
            # working_directory -> package_dir: after this debian stuff works.
            os.rename(working_directory, package_dir)
            if no_build:
                if manifest is not None:
                    write_manifest_to_path(manifest, base_branch)
                return 0
            try:
                build_source_package(package_dir)
                if key_id is not None:
                    sign_source_package(package_dir, key_id)
                if dput is not None:
                    dput_source_package(package_dir, dput)
            finally:
                # package_dir -> working_directory
                # FIXME: may fail in error unwind, masking the original exception.
                os.rename(package_dir, working_directory)
            # Note that this may write a second manifest.
            if manifest is not None:
                write_manifest_to_path(manifest, base_branch)
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir)
        if watch_ppa:
            from bzrlib.plugins.builder.ppa import watch
            target = target_from_dput(dput)
            if not watch(target, self.package, base_branch.deb_version):
                return 2

    def _calculate_package_name(self, recipe_file, package):
        """Calculate the directory name that should be used while debuilding."""
        recipe_name = os.path.basename(recipe_file)
        if recipe_name.endswith(".recipe"):
            recipe_name = recipe_name[:-len(".recipe")]
        return package or recipe_name


def target_from_dput(dput):
    """Convert a dput specification to a LP API specification.

    :param dput: A dput command spec like ppa:team-name.
    :return: A LP API target like team-name/ppa.
    """
    ppa_prefix = 'ppa:'
    if not dput.startswith(ppa_prefix):
        raise errors.BzrCommandError('%r does not appear to be a PPA. '
            'A dput target like \'%suser[/name]\' must be used.'
            % (dput, ppa_prefix))
    base, _, suffix = dput[len(ppa_prefix):].partition('/')
    if not suffix:
        suffix = 'ppa'
    return base + '/' + suffix

