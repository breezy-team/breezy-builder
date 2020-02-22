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

import os
from unittest import TestSuite
from breezy.tests import (
    TestUtil,
    )
from breezy.tests.features import (
    Feature,
    )


class _PristineTarFeature(Feature):

    def feature_name(self):
        return '/usr/bin/pristine-tar'

    def _probe(self):
        return os.path.exists("/usr/bin/pristine-tar")


PristineTarFeature = _PristineTarFeature()


def test_suite():
    loader = TestUtil.TestLoader()
    suite = TestSuite()
    testmod_names = [
            'blackbox',
            'deb_version',
            'recipe',
            ]
    suite.addTest(loader.loadTestsFromModuleNames(
        ["%s.test_%s" % (__name__, i) for i in testmod_names]))
    return suite
