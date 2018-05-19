#!/usr/bin/python

from info import *

from distutils.core import setup

if __name__ == '__main__':
    version = bzr_plugin_version[:3]
    version_string = ".".join([str(x) for x in version])

    setup(name="bzr-builder",
          version=version_string,
          description="Turn a recipe in to a bzr branch",
          author="James Westby",
          author_email="james.westby@canonical.com",
          license="GNU GPL v3",
          url="http://launchpad.net/bzr-builder",
          packages=['breezy.plugins.builder',
                    'breezy.plugins.builder.tests',
                   ],
          package_dir={'breezy.plugins.builder': '.'},
         )
