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

from base64 import standard_b64decode
from StringIO import StringIO
import datetime
from email import utils
import errno
import os
import signal
import shutil
import subprocess
import tempfile

try:
    from debian import changelog, deb822
except ImportError:
    # In older versions of python-debian the main package was named 
    # debian_bundle
    from debian_bundle import changelog, deb822

try:
    get_maintainer = changelog.get_maintainer
except AttributeError:
    # Implementation of get_maintainer was added after 0.1.18 so import same
    # function from backports module if python-debian doesn't have it.
    from bzrlib.plugins.builder.backports import get_maintainer

from bzrlib import (
        errors,
        export as _mod_export,
        lazy_regex,
        osutils,
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


def add_autobuild_changelog_entry(base_branch, basedir, package,
        distribution=None, author_name=None, author_email=None,
        append_version=None):
    """Add a new changelog entry for an autobuild.

    :param base_branch: Recipe base branch
    :param basedir: Base working directory
    :param package: package name
    :param distribution: Optional distribution (defaults to last entry
        distribution)
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
    else:
        if file_found:
            if len(contents.strip()) > 0:
                reason = ("debian/changelog didn't contain any "
                         "parseable stanzas")
            else:
                reason = "debian/changelog was empty"
        else:
            reason = "debian/changelog was not present"
        if distribution is None:
            distribution = DEFAULT_UBUNTU_DISTRIBUTION
    if base_branch.format in (0.1, 0.2, 0.3):
        try:
            base_branch.substitute_changelog_vars(None, cl)
        except SubstitutionUnavailable, e:
            raise errors.BzrCommandError("No previous changelog to "
                    "take the upstream version from as %s was "
                    "used: %s: %s." % (e.name, e.reason, reason))
    # Use debian packaging environment variables
    # or default values if they don't exist
    if author_name is None or author_email is None:
        author_name, author_email = get_maintainer()
        # The python-debian package breaks compatibility at version 0.1.20 by
        # switching to expecting (but not checking for) unicode rather than
        # bytestring inputs. Detect this and decode environment if needed.
        if getattr(changelog.Changelog, "__unicode__", None) is not None:
            enc = osutils.get_user_encoding()
            author_name = author_name.decode(enc)
            author_email = author_email.decode(enc)
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
        not_installed_msg=None, env=None, success_exit_codes=None, indata=None):
    """ Run a command in a subprocess.

    :param command: list with command and parameters
    :param msg: message to display to the user
    :param error_msg: message to display if something fails.
    :param not_installed_msg: the message to display if the command
        isn't available.
    :param env: Optional environment to use rather than os.environ.
    :param success_exit_codes: Exit codes to consider succesfull, defaults to [0].
    :param indata: Data to write to standard input
    """
    def subprocess_setup():
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    trace.note(msg)
    # Hide output if -q is in use.
    quiet = trace.is_quiet()
    if quiet:
        kwargs = {"stderr": subprocess.STDOUT, "stdout": subprocess.PIPE}
    else:
        kwargs = {}
    if env is not None:
        kwargs["env"] = env
    trace.mutter("running: %r", command)
    try:
        proc = subprocess.Popen(command, cwd=basedir,
                stdin=subprocess.PIPE, preexec_fn=subprocess_setup, **kwargs)
    except OSError, e:
        if e.errno != errno.ENOENT:
            raise
        if not_installed_msg is None:
            raise
        raise MissingDependency(msg=not_installed_msg)
    output = proc.communicate(indata)
    if success_exit_codes is None:
        success_exit_codes = [0]
    if proc.returncode not in success_exit_codes:
        if quiet:
            raise errors.BzrCommandError("%s: %s" % (error_msg, output))
        else:
            raise errors.BzrCommandError(error_msg)


def build_source_package(basedir, tgz_check=True):
    command = ["/usr/bin/debuild"]
    if tgz_check:
        command.append("--tgz-check")
    else:
        command.append("--no-tgz-check")
    command.extend(["-i", "-I", "-S", "-uc", "-us"])
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


def force_native_format(working_tree_path, current_format):
    """Make sure a package is a format that supports native packages.

    :param working_tree_path: Path to the package
    """
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
    f = open(control_path, 'r')
    try:
        control = deb822.Deb822(f)
        # Debian policy states package names are [a-z0-9][a-z0-9.+-]+ so ascii
        return control["Source"].encode("ascii")
    finally:
        f.close()


def reconstruct_pristine_tar(dest, delta, dest_filename):
    """Reconstruct a pristine tarball from a directory and a delta.

    :param dest: Directory to pack
    :param delta: pristine-tar delta
    :param dest_filename: Destination filename
    """
    command = ["pristine-tar", "gentar", "-",
               os.path.abspath(dest_filename)]
    _run_command(command, dest,
        "Reconstructing pristine tarball",
        "Generating tar from delta failed",
        not_installed_msg="pristine-tar is not installed",
        indata=delta)


def extract_upstream_tarball(branch, package, version, dest_dir):
    """Extract the upstream tarball from a branch.

    :param branch: Branch with the upstream pristine tar data
    :param package: Package name
    :param version: Package version
    :param dest_dir: Destination directory
    """
    tag_name = "upstream-%s" % version
    revid = branch.tags.lookup_tag(tag_name)
    tree = branch.repository.revision_tree(revid)
    rev = branch.repository.get_revision(revid)
    if 'deb-pristine-delta' in rev.properties:
        uuencoded = rev.properties['deb-pristine-delta']
        dest_filename = "%s_%s.orig.tar.gz" % (package, version)
    elif 'deb-pristine-delta-bz2' in rev.properties:
        uuencoded = rev.properties['deb-pristine-delta-bz2']
        dest_filename = "%s_%s.orig.tar.bz2" % (package, version)
    else:
        uuencoded = None
    if uuencoded is not None:
        delta = standard_b64decode(uuencoded)
        dest = os.path.join(dest_dir, "orig")
        try:
            _mod_export.export(tree, dest, format='dir')
            reconstruct_pristine_tar(dest, delta,
                os.path.join(dest_dir, dest_filename))
        finally:
            if os.path.exists(dest):
                shutil.rmtree(dest)
    else:
        # Default to .tar.gz
        dest_filename = "%s_%s.orig.tar.gz" % (package, version)
        _mod_export.export(tree, os.path.join(dest_dir, dest_filename),
                per_file_timestamps=True)


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
        if self._template_version is None:
            working_directory = os.path.join(working_basedir,
                "%s-direct" % (package_name,))
        else:
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
                    raise errors.BzrCommandError("No control file to "
                            "take the package name from, and --package not "
                            "specified.")
            else:
                package = debian_source_package_name(control_path)
            write_manifest_to_transport(manifest_path, base_branch,
                possible_transports)
            autobuild = (base_branch.deb_version is not None)
            if autobuild:
                # Add changelog also substitutes {debupstream}.
                add_autobuild_changelog_entry(base_branch, working_directory,
                    package, distribution=distribution, 
                    append_version=append_version)
            else:
                if append_version:
                    raise errors.BzrCommandError("--append-version only "
                        "supported for autobuild recipes (with a 'deb-version' "
                        "header)")
            with open(os.path.join(working_directory, "debian", "changelog")) as cl_f:
                contents = cl_f.read()
            cl = changelog.Changelog(file=contents)
            package_name = cl.package
            package_version = cl.version
            package_dir = calculate_package_dir(package_name, package_version,
                working_basedir)
            # working_directory -> package_dir: after this debian stuff works.
            os.rename(working_directory, package_dir)
            try:
                current_format = get_source_format(package_dir)
                if (package_version.debian_version is not None or
                    current_format == "3.0 (quilt)"):
                    # Non-native package
                    try:
                        extract_upstream_tarball(base_branch.branch, package_name,
                            package_version.upstream_version, working_basedir)
                    except errors.NoSuchTag, e:
                        if not allow_fallback_to_native:
                            raise errors.BzrCommandError(
                                "Unable to find the upstream source. Import it "
                                "as tag %s or build with "
                                "--allow-fallback-to-native." % e.tag_name)
                        else:
                            force_native_format(package_dir, current_format)
                if not no_build:
                    build_source_package(package_dir,
                            tgz_check=not allow_fallback_to_native)
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

