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

import argparse
from StringIO import StringIO
import datetime
import os
import shutil
import sys
import tempfile

import breezy.bzr

from breezy import (
    errors,
    lazy_regex,
    transport as _mod_transport,
    urlutils,
    )
from breezy.branch import Branch
from breezy.commands import Command
from breezy.option import Option

from .recipe import (
    BaseRecipeBranch,
    build_tree,
    RecipeParser,
    resolve_revisions,
    SAFE_INSTRUCTIONS,
    )
import debian
from .deb_util import (
    add_autobuild_changelog_entry,
    build_source_package,
    calculate_package_dir,
    changelog,
    debian_source_package_name,
    extract_upstream_tarball,
    force_native_format,
    get_source_format,
    )
from .deb_version import (
    check_expanded_deb_version,
    substitute_branch_vars,
    substitute_time,
    )
from .main import (
    get_old_recipe,
    get_prepared_branch_from_location,
    write_manifest_to_transport,
    )


import breezy.plugins.launchpad


def main():
    """Build a deb based on a 'recipe' or from a branch.

    See "bzr help builder" for more information on what a recipe is.

    If you do not specify a working directory then a temporary
    directory will be used and it will be removed when the command
    finishes.
    """
    parser = argparse.ArgumentParser(
        description="Construct a Debian source tree based on a recipe.")
    parser.add_argument(
        "location", metavar="LOCATION", type=str,
        help="The file system path to the recipe.")
    parser.add_argument(
        "working_basedir", metavar="WORKING-BASEDIR", nargs="?", help=(
            "The path to a working directory.  If not specified, use a "
            "temporary directory."), type=str)
    parser.add_argument(
        "--if-changed-from", metavar="PATH", help=(
            "Only build if the outcome would be different to that "
            "specified in this manifest."), type=str)
    parser.add_argument(
        "--manifest", metavar="PATH", help="Path to write the manifest to.",
        type=str)
    parser.add_argument(
        "--package", help=(
            "The package name to use in the changelog entry.  If not "
            "specified then the package from the previous changelog entry "
            "will be used, so it must be specified if there is no changelog."),
        type=str)
    parser.add_argument(
        "--distribution", help=(
            "The distribution to target.  If not specified then the same "
            "distribution as the last entry in debian/changelog will be "
            "used."),
        type=str)
    parser.add_argument(
        "--no-build", action="store_false", default=True, dest="build",
        help="Just ready the source package and don't actually build it.")
    parser.add_argument(
        "--append-version", help=(
            "Append the specified string to the end of the version used in "
            "debian/changelog."),
        type=str)
    parser.add_argument(
        "--safe", action="store_true", default=False,
        help="Error if the recipe would cause arbitrary code execution.")
    parser.add_argument(
        "--allow-fallback-to-native", action="store_true", default=False,
        help=(
            "Allow falling back to a native package if the upstream tarball "
            "cannot be found."))

    args = parser.parse_args()

    possible_transports = []
    base_branch = get_prepared_branch_from_location(args.location, safe=args.safe,
        possible_transports=possible_transports)
    # Save the unsubstituted version
    template_version = base_branch.deb_version
    if args.if_changed_from is not None:
        old_recipe = get_old_recipe(args.if_changed_from, possible_transports)
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
        sys.stderr.write("Unchanged\n")
        return 0
    if args.working_basedir is None:
        temp_dir = tempfile.mkdtemp(prefix="bzr-builder-")
        args.working_basedir = temp_dir
    else:
        temp_dir = None
        if not os.path.exists(args.working_basedir):
            os.makedirs(args.working_basedir)
    package_name = _calculate_package_name(args.location, args.package)
    if template_version is None:
        working_directory = os.path.join(args.working_basedir,
            "%s-direct" % (package_name,))
    else:
        working_directory = os.path.join(args.working_basedir,
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
            if args.package is None:
                raise errors.BzrCommandError("No control file to "
                        "take the package name from, and --package not "
                        "specified.")
        else:
            args.package = debian_source_package_name(control_path)
        write_manifest_to_transport(manifest_path, base_branch,
            possible_transports)
        autobuild = (base_branch.deb_version is not None)
        if autobuild:
            # Add changelog also substitutes {debupstream}.
            add_autobuild_changelog_entry(base_branch, working_directory,
                args.package, distribution=args.distribution,
                append_version=args.append_version)
        else:
            if args.append_version:
                raise errors.BzrCommandError("--append-version only "
                    "supported for autobuild recipes (with a 'deb-version' "
                    "header)")
        with open(os.path.join(working_directory, "debian", "changelog")) as cl_f:
            contents = cl_f.read()
        cl = changelog.Changelog(file=contents)
        package_name = cl.package
        package_version = cl.version
        package_dir = calculate_package_dir(package_name, package_version,
            args.working_basedir)
        # working_directory -> package_dir: after this debian stuff works.
        os.rename(working_directory, package_dir)
        try:
            current_format = get_source_format(package_dir)
            if (package_version.debian_version is not None or
                current_format == "3.0 (quilt)"):
                # Non-native package
                try:
                    extract_upstream_tarball(base_branch.branch, package_name,
                        package_version.upstream_version, args.working_basedir)
                except errors.NoSuchTag as e:
                    if not args.allow_fallback_to_native:
                        raise errors.BzrCommandError(
                            "Unable to find the upstream source. Import it "
                            "as tag %s or build with "
                            "--allow-fallback-to-native." % e.tag_name)
                    else:
                        force_native_format(package_dir, current_format)
            if args.build:
                build_source_package(package_dir,
                        tgz_check=not args.allow_fallback_to_native)
        finally:
            if args.build:
                # package_dir -> working_directory
                # FIXME: may fail in error unwind, masking the
                # original exception.
                os.rename(package_dir, working_directory)
        # Note that this may write a second manifest.
        if args.manifest is not None:
            write_manifest_to_transport(args.manifest, base_branch,
                possible_transports)
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir)


def _calculate_package_name(recipe_location, package):
    """Calculate the directory name that should be used while debuilding."""
    recipe_name = urlutils.basename(recipe_location)
    if recipe_name.endswith(".recipe"):
        recipe_name = recipe_name[:-len(".recipe")]
    return package or recipe_name


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        sys.stderr.write('ERROR: %s\n' % e)
        sys.exit(3)
    else:
        sys.exit(0)
