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
import tempfile

from breezy import (
    errors,
    lazy_regex,
    trace,
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

import breezy.plugins.launchpad


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

