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

from bzrlib import (
    errors,
    )


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
