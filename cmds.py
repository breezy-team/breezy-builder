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

from StringIO import StringIO
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
    from debian import changelog, deb822
except ImportError:
    # In older versions of python-debian the main package was named 
    # debian_bundle
    from debian_bundle import changelog, deb822

from bzrlib import (
        errors,
        lazy_regex,
        trace,
        transport as _mod_transport,
        urlutils,
        )
from bzrlib.branch import Branch
from bzrlib.commands import Command
from bzrlib.option import Option

from bzrlib.plugins.builder.recipe import (
        BaseRecipeBranch,
        build_tree,
        DebUpstreamVariable,
        RecipeParser,
        resolve_revisions,
        SAFE_INSTRUCTIONS,
        SubstitutionUnavailable,
        )


# The default distribution used by add_autobuild_changelog_entry()
DEFAULT_UBUNTU_DISTRIBUTION = "lucid"


class MissingDependency(errors.BzrError):
    pass


def write_manifest_to_transport(location, base_branch,
        possible_transports=None):
    """Write a manifest to disk.

    :param location: Location to write to
    :param base_branch: Recipe base branch
    """
    child_transport = _mod_transport.get_transport(location,
        possible_transports=possible_transports)
    base_transport = child_transport.clone('..')
    base_transport.create_prefix()
    basename = base_transport.relpath(child_transport.base)
    base_transport.put_bytes(basename, str(base_branch))


def get_branch_from_recipe_location(recipe_location, safe=False,
        possible_transports=None):
    """Return the base branch for the specified recipe.

    :param recipe_location: The URL of the recipe file to retrieve.
    :param safe: if True, reject recipes that would cause arbitrary code
        execution.
    """
    if safe:
        permitted_instructions = SAFE_INSTRUCTIONS
    else:
        permitted_instructions = None
    try:
        (basename, f) = get_recipe_from_location(recipe_location, possible_transports)
    except errors.NoSuchFile:
        raise errors.BzrCommandError("Specified recipe does not exist: "
                "%s" % recipe_location)
    try:
        parser = RecipeParser(f, filename=recipe_location)
    finally:
        f.close()
    return parser.parse(permitted_instructions=permitted_instructions)


def get_branch_from_branch_location(branch_location, possible_transports=None,
        revspec=None):
    """Return the base branch for the branch location.

    :param branch_location: The URL of the branch to retrieve.
    """
    # Make sure it's actually a branch
    Branch.open(branch_location)
    return BaseRecipeBranch(branch_location, None,
        RecipeParser.NEWEST_VERSION, revspec=revspec)


def get_old_recipe(if_changed_from, possible_transports=None):
    try:
        (basename, f) = get_recipe_from_location(if_changed_from, possible_transports)
    except errors.NoSuchFile:
        return None
    try:
        old_recipe = RecipeParser(f,
                filename=if_changed_from).parse()
    finally:
        f.close()
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


def add_autobuild_changelog_entry(base_branch, basedir, distribution=None,
        package=None, author_name=None, author_email=None,
        append_version=None):
    """Add a new changelog entry for an autobuild.

    :param base_branch: Recipe base branch
    :param basedir: Base working directory
    :param distribution: Optional distribution (defaults to last entry
        distribution)
    :param package: Optional package name (defaults to last entry package name)
    :param author_name: Name of the build requester
    :param author_email: Email of the build requester
    :param append_version: Optional version suffix to add
    """
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
        if distribution is None:
            distribution = DEFAULT_UBUNTU_DISTRIBUTION
    try:
        base_branch.substitute_debupstream(cl)
    except SubstitutionUnavailable:
        raise errors.BzrCommandError("No previous changelog to "
                "take the upstream version from as %s was "
                "used: %s." % (DebUpstreamVariable.name, reason))
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


def calculate_package_dir(package_name, package_version, working_basedir):
    """Calculate the directory name that should be used while debuilding.

    :param base_branch: Recipe base branch
    :param package_version: Version of the package
    :param package_name: Package name
    :param working_basedir: Base directory
    """
    package_basedir = "%s-%s" % (package_name, package_version.upstream_version)
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


def build_source_package(basedir, no_tgz_check=False):
    command = ["/usr/bin/debuild", "-i", "-I", "-S", "-uc", "-us"]
    if no_tgz_check:
        command.append("--no-tgz-check")
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


launchpad_recipe_re = lazy_regex.lazy_compile(
    r'^https://code.launchpad.net/~(.*)/\+recipe/(.*)$')


def get_recipe_from_launchpad(username, recipe_name, location):
    """Load a recipe from Launchpad.

    :param username: The launchpad user name
    :param recipe_name: Recipe name
    :param location: Original location (used for error reporting)
    :return: Text of the recipe
    """
    from launchpadlib.launchpad import Launchpad
    lp = Launchpad.login_with("bzr-builder", "production")
    try:
        person = lp.people[username]
    except KeyError:
        raise errors.NoSuchFile(location,
            "No such Launchpad user %s" % username)
    recipe = person.getRecipe(name=recipe_name)
    if recipe is None:
        raise errors.NoSuchFile(location,
            "Launchpad user %s has no recipe %s" % (
            username, recipe_name))
    return recipe.recipe_text


def get_recipe_from_location(location, possible_transports=None):
    """Open a recipe as a file-like object from a URL.

    :param location: The recipe location
    :param possible_transports: Possible transports to use
    :return: Tuple with basename and file-like object
    """
    m = launchpad_recipe_re.match(location)
    if m:
        (username, recipe_name) = m.groups()
        text = get_recipe_from_launchpad(username, recipe_name,
            location)
        return (recipe_name, StringIO(text))
    child_transport = _mod_transport.get_transport(location,
        possible_transports=possible_transports)
    recipe_transport = child_transport.clone('..')
    basename = recipe_transport.relpath(child_transport.base)
    return basename, recipe_transport.get(basename)


class cmd_build(Command):
    """Build a tree based on a branch or a recipe.

    Pass the path of a recipe file or a branch to build and the directory to
    work in.

    See "bzr help builder" for more information on what a recipe is.
    """
    takes_args = ["location", "working_directory"]
    takes_options = [
            Option('manifest', type=str, argname="path",
                   help="Path to write the manifest to."),
            Option('if-changed-from', type=str, argname="path",
                   help="Only build if the outcome would be different "
                        "to that specified in the specified manifest."),
            'revision',
                    ]

    def _get_prepared_branch_from_location(self, location,
            if_changed_from=None, safe=False, possible_transports=None,
            revspec=None):
        """Common code to prepare a branch and do substitutions.

        :param location: a path to a recipe file or branch to work from.
        :param if_changed_from: an optional location of a manifest to
            compare the recipe against.
        :param safe: if True, reject recipes that would cause arbitrary code
            execution.
        :return: A tuple with (retcode, base_branch). If retcode is None
            then the command execution should continue.
        """
        try:
            base_branch = get_branch_from_recipe_location(location, safe=safe,
                possible_transports=possible_transports)
        except (_mod_transport.LateReadError, errors.ReadError):
            # Presume unable to read means location is a directory rather than a file
            base_branch = get_branch_from_branch_location(location,
                possible_transports=possible_transports)
        else:
            if revspec is not None:
                raise errors.BzrCommandError("--revision only supported when "
                    "building from branch")
        time = datetime.datetime.utcnow()
        base_branch.substitute_time(time)
        old_recipe = None
        if if_changed_from is not None:
            old_recipe = get_old_recipe(if_changed_from, possible_transports)
        # Save the unsubstituted version for dailydeb.
        self._template_version = base_branch.deb_version
        changed = resolve_revisions(base_branch, if_changed_from=old_recipe)
        if not changed:
            trace.note("Unchanged")
            return 0, base_branch
        return None, base_branch

    def run(self, location, working_directory, manifest=None,
            if_changed_from=None, revision=None):
        if revision is not None and len(revision) > 0:
            if len(revision) != 1:
                raise errors.BzrCommandError("only a single revision can be "
                    "specified")
            revspec = revision[0]
        else:
            revspec = None
        possible_transports = []
        result, base_branch = self._get_prepared_branch_from_location(location,
            if_changed_from=if_changed_from,
            possible_transports=possible_transports, revspec=revspec)
        if result is not None:
            return result
        manifest_path = manifest or os.path.join(working_directory,
                        "bzr-builder.manifest")
        build_tree(base_branch, working_directory)
        write_manifest_to_transport(manifest_path, base_branch,
            possible_transports)


def debian_source_package_name(control_path):
    """Open a debian control file and extract the package name.

    """
    with open(control_path, 'r') as f:
        control = deb822.Deb822(f)
        return control["Source"]


def extract_upstream_tarball(branch, package, version, dest_dir):
    """Extract the upstream tarball from a branch.

    :param branch: Branch with the upstream pristine tar data
    :param package: Package name
    :param version: Package version
    :param dest_dir: Destination directory
    """
    from bzrlib.plugins.builder.pristinetar import reconstruct_revision_tarball
    tag_name = "upstream-%s" % version
    revid = branch.tags.lookup_tag(tag_name)
    reconstruct_revision_tarball(branch.repository, revid, package, version,
        dest_dir)


class cmd_dailydeb(cmd_build):
    """Build a deb based on a 'recipe' or from a branch.

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
                Option("allow-fallback-to-native",
                    help="Allow falling back to a native package if the upstream "
                         "tarball can not be found."),
            ]

    takes_args = ["location", "working_basedir?"]

    def run(self, location, working_basedir=None, manifest=None,
            if_changed_from=None, package=None, distribution=None,
            dput=None, key_id=None, no_build=None, watch_ppa=False,
            append_version=None, safe=False, allow_fallback_to_native=False):

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

        possible_transports = []
        result, base_branch = self._get_prepared_branch_from_location(location,
            if_changed_from=if_changed_from, safe=safe,
            possible_transports=possible_transports)
        if result is not None:
            return result
        if working_basedir is None:
            temp_dir = tempfile.mkdtemp(prefix="bzr-builder-")
            working_basedir = temp_dir
        else:
            temp_dir = None
            if not os.path.exists(working_basedir):
                os.makedirs(working_basedir)
        package_name = self._calculate_package_name(location, package)
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
            control_path = os.path.join(working_directory, "debian", "control")
            if not os.path.exists(control_path):
                if package is None:
                    raise errors.BzrCommandError("Missing debian/control file to "
                        "read package name from.")
                package = debian_source_package_name(control_path)
            write_manifest_to_transport(manifest_path, base_branch,
                possible_transports)
            autobuild = (base_branch.deb_version is not None)
            if autobuild:
                # Add changelog also substitutes {debupstream}.
                add_autobuild_changelog_entry(base_branch, working_directory,
                    distribution=distribution, package=package,
                    append_version=append_version)
            else:
                if append_version:
                    raise errors.BzrCommandError("--append-version only "
                        "supported for autobuild recipes (with a 'deb-version' "
                        "header)")
            with open(os.path.join(working_directory, "debian", "changelog")) as cl_f:
                contents = cl_f.read()
            cl = changelog.Changelog(file=contents)
            package_version = cl.version
            package_dir = calculate_package_dir(package_name, package_version,
                working_basedir)
            # working_directory -> package_dir: after this debian stuff works.
            os.rename(working_directory, package_dir)
            if no_build:
                if manifest is not None:
                    write_manifest_to_transport(manifest, base_branch,
                        possible_transports)
                return 0
            if package_version.debian_revision is not None:
                # Non-native package
                try:
                    extract_upstream_tarball(base_branch.branch, package_name,
                        package_version.upstream_version, working_basedir)
                except errors.NoSuchTag:
                    if not allow_fallback_to_native:
                        raise
                    else:
                        force_native_format(working_directory)
            try:
                build_source_package(package_dir,
                        no_tgz_check=allow_fallback_to_native)
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
                write_manifest_to_transport(manifest, base_branch,
                    possible_transports)
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir)
        if watch_ppa:
            from bzrlib.plugins.builder.ppa import watch
            (owner, archive) = target_from_dput(dput)
            if not watch(owner, archive, package_name, base_branch.deb_version):
                return 2

    def _calculate_package_name(self, recipe_location, package):
        """Calculate the directory name that should be used while debuilding."""
        recipe_name = urlutils.basename(recipe_location)
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
    return base, suffix

