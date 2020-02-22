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
import os
import sys

import breezy.bzr

from .main import (
    get_prepared_branch_from_location,
    get_old_recipe,
    write_manifest_to_transport,
    )

from .recipe import (
    build_tree,
    resolve_revisions,
    )

import breezy.plugins.launchpad  # noqa: F401


def main():
    """Build a tree based on a branch or a recipe.

    Pass the path of a recipe file or a branch to build and the directory to
    work in.

    See "bzr help builder" for more information on what a recipe is.
    """
    parser = argparse.ArgumentParser(
        description="Construct a Debian source tree based on a recipe.")
    parser.add_argument(
        "location", metavar="LOCATION", type=str,
        help="The file system path to the recipe.")
    parser.add_argument(
        "working_basedir", metavar="WORKING-BASEDIR", type=str, help=(
            "The path to a working directory.  If not specified, use a "
            "temporary directory."))
    parser.add_argument(
        "--manifest", metavar="PATH", help="Path to write the manifest to.")
    parser.add_argument(
        "--revision", metavar="REVISION", help="Revision to build.")
    parser.add_argument(
        "--if-changed-from", metavar="PATH", help=(
            "Only build if the outcome would be different to that "
            "specified in this manifest."), type=str)

    args = parser.parse_args()

    if args.revision is not None:
        revspec = args.revision
    else:
        revspec = None
    possible_transports = []
    base_branch = get_prepared_branch_from_location(
        args.location, possible_transports=possible_transports,
        revspec=revspec)
    if args.if_changed_from is not None:
        old_recipe = get_old_recipe(args.if_changed_from, possible_transports)
    else:
        old_recipe = None
    changed = resolve_revisions(base_branch, if_changed_from=old_recipe)
    if not changed:
        sys.stderr.write("Unchanged\n")
        return 0
    manifest_path = args.manifest or os.path.join(
        args.working_basedir, "bzr-builder.manifest")
    build_tree(base_branch, args.working_basedir)
    write_manifest_to_transport(
        manifest_path, base_branch, possible_transports)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        sys.stderr.write('ERROR: %s\n' % e)
        sys.exit(3)
    else:
        sys.exit(0)
