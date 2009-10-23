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

from optparse import OptionParser
import os
import sys
import time

from launchpadlib.launchpad import (
    Launchpad, STAGING_SERVICE_ROOT, EDGE_SERVICE_ROOT)
from launchpadlib.credentials import Credentials

def watch(target, package_name, version):
    """Watch a package build.

    :return: 0 once the package built and published completely ok or 2
        otherwise.
    """
    # See https://help.launchpad.net/API
    credentials = Credentials()
    oauth_file = os.path.expanduser('~/.cache/edge_oauth.txt')
    try:
        credentials.load(open(oauth_file))
        launchpad = Launchpad(credentials, EDGE_SERVICE_ROOT)
    except Exception:
        cachedir = os.path.expanduser("~/.launchpadlib/cache/")
        launchpad = Launchpad.get_token_and_login('get-build-status', EDGE_SERVICE_ROOT, cachedir)
        launchpad.credentials.save(file(oauth_file, "w"))
    
    try:
        owner_name, archive_name = target.split('/', 2)
    except ValueError:
            print "E: Failed to parse archive identifier."
            print "Syntax of target archive: <owner>/<archive>"
            sys.exit(1)
    
    owner = launchpad.people[owner_name]
    archive = owner.getPPAByName(name=archive_name)
    end_states = ['failedtobuild', 'fullybuilt']
    important_arches = ['amd64', 'i386', 'lpia', 'armel']
    print "Waiting for", version, "of", package_name, "to build."
    start = time.time()
    while True:
        sourceRecords = [s for s in
            archive.getPublishedSources(source_name=package_name)]
        # print [s.source_package_version for s in sourceRecords]
        sourceRecords = [s for s in sourceRecords
            if s.source_package_version == version]
        if not sourceRecords:
            if time.time() - 900 > start:
                # Over 15 minutes and no source yet, upload FAIL.
                raise errors.BzrCommandError("No source record in %s for "
                    "package %s=%s after 15 minutes." % (target, package_name,
                    version))
                return 2
            time.sleep(60)
            continue
        pkg = sourceRecords[0]
        if pkg.status.lower() not in ('published', 'pending'):
            time.sleep(60)
            continue
        source_id = str(pkg.self).rsplit('/', 1)[1]
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
            extra = ', '.join(missing)
        else:
            extra = ''
        print "%s: %s" % (pkg.display_name, buildSummaries['status']), extra
        time.sleep(60)
    print "%s: %s" % (pkg.display_name, buildSummaries['status'])
    result = 0
    if pkg.status.lower() != 'published':
        result = 2
    if buildSummaries['status'] != 'FULLYBUILT':
        if buildSummaries['status'] == 'NEEDSBUILD':
            # We're stopping early cause the important_arches are built.
            builds = pkg.getBuilds()
            for build in builds:
                if build.arch_tag in important_arches:
                    if build.buildstate != 'Successfully built':
                        result = 2
        else:
            result = 2
    return result
