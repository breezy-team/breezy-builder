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
import os
import shutil
import tempfile

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
    RecipeParser,
    resolve_revisions,
    SAFE_INSTRUCTIONS,
    )



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


def get_prepared_branch_from_location(location,
        safe=False, possible_transports=None,
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
    return base_branch


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
        base_branch = get_prepared_branch_from_location(location,
            possible_transports=possible_transports, revspec=revspec)
        if if_changed_from is not None:
            old_recipe = get_old_recipe(if_changed_from, possible_transports)
        else:
            old_recipe = None
        changed = resolve_revisions(base_branch, if_changed_from=old_recipe)
        if not changed:
            trace.note("Unchanged")
            return 0
        manifest_path = manifest or os.path.join(working_directory,
                        "bzr-builder.manifest")
        build_tree(base_branch, working_directory)
        write_manifest_to_transport(manifest_path, base_branch,
            possible_transports)


class cmd_dailydeb(Command):
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
        try:
            try:
                import debian
            except ImportError:
                # In older versions of python-debian the main package was named 
                # debian_bundle
                import debian_bundle
        except ImportError:
            raise errors.BzrCommandError("The 'debian' python module "
                "is required for 'bzr dailydeb'. Install the "
                "python-debian package.")

        from bzrlib.plugins.builder.deb_util import (
            add_autobuild_changelog_entry,
            build_source_package,
            calculate_package_dir,
            changelog,
            debian_source_package_name,
            dput_source_package,
            extract_upstream_tarball,
            force_native_format,
            get_source_format,
            sign_source_package,
            target_from_dput,
            )
        from bzrlib.plugins.builder.deb_version import (
            check_expanded_deb_version,
            substitute_branch_vars,
            substitute_time,
            )

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
        base_branch = get_prepared_branch_from_location(location, safe=safe,
            possible_transports=possible_transports)
        # Save the unsubstituted version
        template_version = base_branch.deb_version
        if if_changed_from is not None:
            old_recipe = get_old_recipe(if_changed_from, possible_transports)
        else:
            old_recipe = None
        if base_branch.deb_version is not None:
            time = datetime.datetime.utcnow()
            substitute_time(base_branch, time)
            changed = resolve_revisions(base_branch, if_changed_from=old_recipe,
                substitute_branch_vars=substitute_branch_vars)
            check_expanded_deb_version(base_branch)
        else:
            changed = resolve_revisions(base_branch, if_changed_from=old_recipe)
        if not changed:
            trace.note("Unchanged")
            return 0
        if working_basedir is None:
            temp_dir = tempfile.mkdtemp(prefix="bzr-builder-")
            working_basedir = temp_dir
        else:
            temp_dir = None
            if not os.path.exists(working_basedir):
                os.makedirs(working_basedir)
        package_name = self._calculate_package_name(location, package)
        if template_version is None:
            working_directory = os.path.join(working_basedir,
                "%s-direct" % (package_name,))
        else:
            working_directory = os.path.join(working_basedir,
                "%s-%s" % (package_name, template_version))
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

