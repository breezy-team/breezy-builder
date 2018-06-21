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

"""Debian-specific utility functions."""

from base64 import standard_b64decode
from email import utils
import errno
import os
import shutil
import signal
import subprocess

from breezy import (
    errors,
    export as _mod_export,
    osutils,
    trace,
    )

from .deb_version import substitute_changelog_vars
from .recipe import (
    SubstitutionUnavailable,
    )

try:
    from debian import changelog, deb822
except ImportError:
    # In older versions of python-debian the main package was named 
    # debian_bundle
    from debian_bundle import changelog, deb822


get_maintainer = changelog.get_maintainer

# The default distribution used by add_autobuild_changelog_entry()
DEFAULT_UBUNTU_DISTRIBUTION = "lucid"


class MissingDependency(errors.BzrError):
    pass


def debian_source_package_name(control_path):
    """Open a debian control file and extract the package name.

    """
    with open(control_path, 'r') as f:
        control = deb822.Deb822(f)
        # Debian policy states package names are [a-z0-9][a-z0-9.+-]+ so ascii
        return control["Source"].encode("ascii")


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
    tag_names = ["upstream-%s" % version, "upstream/%s" % version]
    for tag_name in tag_names:
        try:
            revid = branch.tags.lookup_tag(tag_name)
        except errors.NoSuchTag:
            pass
        else:
            break
    else:
        raise errors.NoSuchTag(tag_names[0])
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
            substitute_changelog_vars(base_branch, None, cl)
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
    with open(os.path.join(path, "debian", "source", "format"), 'w') as f:
        f.write("3.0 (native)\n")


def force_native_format(working_tree_path, current_format):
    """Make sure a package is a format that supports native packages.

    :param working_tree_path: Path to the package
    """
    if current_format == "3.0 (quilt)":
        convert_3_0_quilt_to_native(working_tree_path)
    elif current_format not in ("1.0", "3.0 (native)"):
        raise errors.BzrCommandError("Unknown source format %s" %
                                     current_format)
