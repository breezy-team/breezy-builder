check: tests2 tests3 flake8

flake8:
	flake8

tests3:
	PYTHONPATH=$$PYTHONPATH:$$(pwd) python3 -m unittest brzbuildrecipe.tests.test_suite

tests2:
	PYTHONPATH=$$PYTHONPATH:$$(pwd) python2 -m unittest brzbuildrecipe.tests.test_suite

.PHONY: flake8 tests3 tests2 check
