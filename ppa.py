# ppa support for bzr builder.
#
# Copyright: Canonical Ltd. (C) 2009
#
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
import time


from launchpadlib.launchpad import (
    Launchpad,
    EDGE_SERVICE_ROOT,
    )
from launchpadlib.credentials import Credentials

from bzrlib import (
    errors,
    trace,
    )


def get_lp():
    credentials = Credentials()
    oauth_file = os.path.expanduser('~/.cache/launchpadlib/bzr-builder')
    if os.path.exists(oauth_file):
        f = open(oauth_file)
        try:
            credentials.load(f)
        finally:
            f.close()
        launchpad = Launchpad(credentials, EDGE_SERVICE_ROOT)
    else:
        launchpad = Launchpad.get_token_and_login('bzr-builder',
                EDGE_SERVICE_ROOT)
        f = open(oauth_file, 'wb')
        try:
            launchpad.credentials.save(f)
        finally:
            f.close()
    return launchpad


def watch(owner_name, archive_name, package_name, version):
    """Watch a package build.

    :return: True once the package built and published, or False if it fails
        or there is a timeout waiting.
    """
    version = str(version)
    trace.note("Logging into Launchpad")

    launchpad = get_lp()
    owner = launchpad.people[owner_name]
    archive = owner.getPPAByName(name=archive_name)
    end_states = ['FAILEDTOBUILD', 'FULLYBUILT']
    important_arches = ['amd64', 'i386', 'lpia', 'armel']
    trace.note("Waiting for version %s of %s to build." % (version, package_name))
    start = time.time()
    while True:
        sourceRecords = list(archive.getPublishedSources(
            source_name=package_name, version=version))
        if not sourceRecords:
            if time.time() - 900 > start:
                # Over 15 minutes and no source yet, upload FAIL.
                raise errors.BzrCommandError("No source record in %s/%s for "
                    "package %s=%s after 15 minutes." % (owner_name,
                        archive_name, package_name, version))
                return False
            trace.note("Source not available yet - waiting.")
            time.sleep(60)
            continue
        pkg = sourceRecords[0]
        if pkg.status.lower() not in ('published', 'pending'):
            trace.note("Package status: %s" % (pkg.status,))
            time.sleep(60)
            continue
        # FIXME: LP should export this as an attribute.
        source_id = pkg.self_link.rsplit('/', 1)[1]
        buildSummaries = archive.getBuildSummariesForSourceIds(
            source_ids=[source_id])[source_id]
        if buildSummaries['status'] in end_states:
            break
        if buildSummaries['status'] == 'NEEDSBUILD':
            # We ignore non-virtual PPA architectures that are sparsely
            # supplied with buildds.
            missing = []
            for build in buildSummaries['builds']:
                arch = build['arch_tag']
                if arch in important_arches:
                    missing.append(arch)
            if not missing:
                break
            extra = ' on ' + ', '.join(missing)
        else:
            extra = ''
        trace.note("%s is still in %s%s" % (pkg.display_name,
                    buildSummaries['status'], extra))
        time.sleep(60)
    trace.note("%s is now %s" % (pkg.display_name, buildSummaries['status']))
    result = True
    if pkg.status.lower() != 'published':
        result = False # should this perhaps keep waiting?
    if buildSummaries['status'] != 'FULLYBUILT':
        if buildSummaries['status'] == 'NEEDSBUILD':
            # We're stopping early cause the important_arches are built.
            builds = pkg.getBuilds()
            for build in builds:
                if build.arch_tag in important_arches:
                    if build.buildstate != 'Successfully built':
                        result = False
        else:
            result = False
    return result
