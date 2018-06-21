# brz-builder: a brz plugin to constuct trees based on recipes
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

"""brz-build-recipe allows you to construct a branch from a 'recipe'.

The recipe is a series of pointers to branches and instructions for how they
should be combined. There are two ways to combine branches, by merging, and
by nesting, allowing much flexibility.

A recipe is just a text file that starts with a line such as::

  # bzr-builder format 0.3 deb-version 1.0+{revno}-{revno:packaging}

The format specifier is there to allow the syntax to be changed in later
versions, and the meaning of "deb-version" will be explained later.

The next step is the define the base branch, this is the branch that will
be places at the root, e.g. just put::

  lp:foo

to use the trunk of "foo" hosted on Launchpad.

Next comes any number of lines of other branches to be merged in, but using
a slightly different format. To merge a branch in to the base specify
something like::

  merge packaging lp:~foo-dev/foo/packaging

which specifies we are merging a branch we will refer to as "packaging", which
can be found at the given URI. The name you give to the branch as the second
item doesn't have to match anything else, it's just an identifier specific
to the recipe.

If you wish to nest a branch then you use a similar line::

  nest artwork lp:foo-images images

This specifies that we are nesting the branch at lp:foo-images, which we will
call "artwork", and we will place it locally in to the "images" directory.

You can then continue in this fashion for as many branches as you like. It
is also possible to nest and merge branches into nested branches. For example
to merge a branch in to the "artwork" branch we put the following on the line
below that one, indented by two spaces::

  merge artwork-fixes lp:~bob/foo-images/fix-12345

which will merge Bob's fixes branch into the "artwork" branch which we nested
at "images".

It is also possible to specify a particular revision of a branch by appending
a revisionspec to the line. For instance::

  nest docs lp:foo-docs doc tag:1.0

will nest the revision pointed to by the "1.0" tag of that branch. The format
for the revisionspec is identical to that taken by the "--revision" argument
to many brz commands. See "brz help revisionspec" for details.

You can also merge specific subdirectories from a branch with a "nest-part"
line like

  nest-part packaging lp:~foo-dev/foo/packaging debian

which specifies that the only the debian/ subdirectory should be merged.  This
works even if the branches share no revision history.  You can optionally
specify the subdirectory and revision in the target with a line like

  nest-part libfoo lp:libfoo src lib/foo tag:release-1.2

which will put the "src" directory of libfoo in "lib/foo", using the revision
of libfoo tagged "release-1.2".

It is also possible to run an arbitrary command at a particular point in the
construction process. For example::

  run autoreconf -i

will run autotools at a particular point. Doing things with branches is usually
preferred, but sometimes it is the easier or only way to achieve something.
Note that you usually shouldn't rely on having general Internet access when
assembling the recipe, so commands that require it should be avoided.

You can then build this branch by running::

  brz build foo.recipe working-dir

(assuming you saved it as foo.recipe in your current directory).

Once the command finished it will have placed the result in "working-dir".

It is also possible to produce Debian source packages from a recipe, assuming
that one of the branches in the recipe contains some appropriate packaging.
You can do this using the "brz dailydeb" command, which takes the same
arguments as "build". Only this time in the working dir you will find a source
package and a directory containing the code that the packages was built from
once it is done. Also take a look at the "--key-id" and "--dput" arguments to
have "brz dailydeb" sign and upload the source package somewhere.

To build Debian source package that you desire you should make sure that
"deb-version" is set to an appropriate value on the first line of your
recipe. This will be used as the version number of the package. The
value you put there also allows for substitution of values in to it based
on various things when the recipe is processed:

  * {time} will be substituted with the current date and time, such as
    200908191512.
  * {date} will be substituted with just the current date, such as
    20090819.
  * {revno} will be the revno of the base branch (the first specified).
  * {revno:<branch name>} will be substituted with the revno for the
    branch named <branch name> in the recipe.
  * {debupstream}/{debupstream:<branch name>} will be replaced by the upstream
    portion of the version number taken from debian/changelog in the branch.
    For example, if debian/changelog has a version number of "1.0-1" then this
    would evaluate to "1.0".
  * {debupstream-base}/{debupstream-base:<branch name>} will be replaced by the
    upstream portion of the version number taken from debian/changelog in the
    branch, with any VCS markers stripped.  For example, if debian/changelog
    has a version number of "1.0~brz43-1" then this would evaluate to "1.0~".
    For any upstream versions without a VCS marker, a "+" is added to the
    version ("1.0-1" becomes "1.0+").
  * {debversion}/{debversion:<branch name>} will be substituted with
    the exact version string from debian/changelog in the branch.
  * {revtime}/{revtime:<branch name>} will be substituted with the date and
    time of the revision that was built, such as 201108191512.
  * {revdate}/{revdate:<branch name>} will be substituted with the date
    of the revision that was built, such as 20111222.
  * {latest-tag}/{latest-tag:<branch name>} will be replaced with the
    name of the tag found on the most recent revision in the
    branch mainline that has a tag.
  * {git-commit}/{git-commit:<branch name>} will be substituted with the last 7
    characters of the SHA1 checksum of the revision that was built, if the
    revision was imported from a Git repository.
  * {svn-revno}/{svn-revno:<branch name>} will be substituted with the
    Subversion revision number of the revision that was built, if the
    revision was imported from a Subversion repository.

Instruction syntax summary:

  * nest NAME BRANCH TARGET-DIR [REVISION]
  * merge NAME BRANCH [REVISION]
  * nest-part NAME BRANCH SUBDIR [TARGET-DIR [REVISION]]
  * run COMMAND

Format versions:

  0.1 - original format.
  0.2 - added "run" instruction.
  0.3 - added "nest-part" instruction.
  0.4 - made "deb-version" optional, added several new substitution variables.
        {debupstream} now only looks for changelog in the root branch, not the
        resulting tree
"""

from __future__ import absolute_import


def test_suite():
    from unittest import TestSuite
    from . import tests
    result = TestSuite()
    result.addTest(tests.test_suite())
    return result
