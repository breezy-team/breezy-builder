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

    :return: True once the package built and published completely ok or False
        otherwise.
    """
    # See https://help.launchpad.net/API
    credentials = Credentials()
    oauth_file = os.path.expanduser('~/.cache/edge_oauth.txt')
    try:
        credentials.load(open(oauth_file))
        launchpad = Launchpad(credentials, EDGE_SERVICE_ROOT)
    except:
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
    print "Waiting for", version, "of", package_name, "to build."
    while True:
        sourceRecords = [s for s in
            archive.getPublishedSources(source_name=package_name)]
        # print [s.source_package_version for s in sourceRecords]
        sourceRecords = [s for s in sourceRecords
            if s.source_package_version == version]
        if not sourceRecords:
            time.sleep(60)
            continue
        pkg = sourceRecords[0]
        if pkg.status.lower() not in ('published', 'pending'):
            time.sleep(60)
            continue
        source_id = str(pkg.self).rsplit('/', 1)[1]
        buildSummaries = archive.getBuildSummariesForSourceIds(
            source_ids=[source_id])[source_id]
        print "%s: %s" % (pkg.display_name, buildSummaries['status'])
        if buildSummaries['status'] in end_states:
            break
        if buildSummaries['status'] == 'NEEDSBUILD':
            # We ignore non-virtual PPA architectures that are sparsely
            # supplied with buildds.
            wait = False
            for build in buildSummaries['builds']:
                if build['arch_tag'] in ['amd64', 'i386', 'lpia', 'armel']:
                    wait = True
            if not wait:
                break
        time.sleep(60)
    return (buildSummaries['status'] == 'fullybuilt' and 
        pkg.status.lower() == 'published')
