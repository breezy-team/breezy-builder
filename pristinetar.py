# bzr-builder: a bzr plugin to constuct trees based on recipes
# Copyright 2011 Canonical Ltd.

# This program is free software: you can redistribute it and/or modify it 
# under the terms of the GNU General Public License version 3, as published 
# by the Free Software Foundation.

# This program is distributed in the hope that it will be useful, but 
# WITHOUT ANY WARRANTY; without even the implied warranties of 
# MERCHANTABILITY, SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR 
# PURPOSE.  See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along 
# with this program.  If not, see <http://www.gnu.org/licenses/>.

from base64 import standard_b64decode
from bzrlib.errors import BzrError
from bzrlib.export import export

import errno
import os
import signal
import shutil
import subprocess
import tempfile


class PristineTarError(BzrError):
    _fmt = 'There was an error using pristine-tar: %(error)s.'

    def __init__(self, error):
        BzrError.__init__(self, error=error)


def reconstruct_revision_tarball(repository, revid, package, version,
        dest_dir):
    """Reconstruct a pristine-tar tarball from a bzr revision."""
    tree = repository.revision_tree(revid)
    tmpdir = tempfile.mkdtemp(prefix="builddeb-pristine-")
    try:
        dest = os.path.join(tmpdir, "orig")
        rev = repository.get_revision(revid)
        if 'deb-pristine-delta' in rev.properties:
            uuencoded = rev.properties['deb-pristine-delta']
            dest_filename = "%s_%s.orig.tar.gz" % (package, version)
        elif 'deb-pristine-delta-bz2' in rev.properties:
            uuencoded = rev.properties['deb-pristine-delta-bz2']
            dest_filename = "%s_%s.orig.tar.bz2" % (package, version)
        else:
            uuencoded = None
        if uuencoded is not None:
            delta = standard_b64decode(uuencoded)
            export(tree, dest, format='dir')
            reconstruct_pristine_tar(dest, delta,
                os.path.join(dest_dir, dest_filename))
        else:
            # Default to .tar.gz
            dest_filename = "%s_%s.orig.tar.gz" % (package, version)
            export(tree, os.path.join(dest_dir, dest_filename),
                    require_per_file_timestamps=True)
    finally:
        shutil.rmtree(tmpdir)


def reconstruct_pristine_tar(dest, delta, dest_filename):
    """Reconstruct a pristine tarball from a directory and a delta.

    :param dest: Directory to pack
    :param delta: pristine-tar delta
    :param dest_filename: Destination filename
    """
    def subprocess_setup():
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    command = ["pristine-tar", "gentar", "-",
               os.path.abspath(dest_filename)]
    try:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE,
                cwd=dest, preexec_fn=subprocess_setup,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError, e:
        if e.errno == errno.ENOENT:
            raise PristineTarError("pristine-tar is not installed")
        else:
            raise
    (stdout, stderr) = proc.communicate(delta)
    if proc.returncode != 0:
        raise PristineTarError("Generating tar from delta failed: %s" % stdout)
