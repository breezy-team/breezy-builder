#!/usr/bin/python

from setuptools import setup

version = (0, 7, 4, 'dev', 0)
version_string = ".".join([str(x) for x in version])

setup(name="brz-build-recipe",
      version=version_string,
      description="Turn a recipe in to a bzr branch",
      author="James Westby",
      author_email="james.westby@canonical.com",
      license="GNU GPL v3",
      url="http://launchpad.net/brz-builder",
      packages=['brzbuildrecipe',
                'brzbuildrecipe.tests',
               ],
      scripts = ['bin/brz-build-daily-recipe', 'bin/brz-build-recipe'],
      package_dir={'brzbuildrecipe': 'brzbuildrecipe'},
      install_requires=['breezy', 'python-debian', 'python-dateutil'],
      test_requires=['fixtures', 'testtools'],
     )
