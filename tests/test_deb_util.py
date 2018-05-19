# bzr-builder: a bzr plugin to construct trees based on recipes
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

from breezy.plugins.builder.deb_util import target_from_dput
from breezy.tests import (
        TestCase,
        )


class TestTargetFromDPut(TestCase):

    def test_default_ppa(self):
        self.assertEqual(('team-name', 'ppa'), target_from_dput('ppa:team-name'))

    def test_named_ppa(self):
        self.assertEqual(('team', 'ppa2'), target_from_dput('ppa:team/ppa2'))
