#!/usr/bin/python

from distutils.core import setup

if __name__ == '__main__':
    setup(name="bzr-builder",
          version="0.7.2",
          description="Turn a recipe in to a bzr branch",
          author="James Westby",
          author_email="james.westby@canonical.com",
          license="GNU GPL v3",
          url="http://launchpad.net/bzr-builder",
          packages=['bzrlib.plugins.builder',
                    'bzrlib.plugins.builder.tests',
                   ],
          package_dir={'bzrlib.plugins.builder': '.'},
         )
