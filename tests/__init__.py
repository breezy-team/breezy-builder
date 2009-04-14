from unittest import TestSuite
from bzrlib.tests import TestUtil

def test_suite():
    loader = TestUtil.TestLoader()
    suite = TestSuite()
    testmod_names = [
            'test_blackbox',
            'test_recipe',
            ]
    suite.addTest(loader.loadTestsFromModuleNames(["%s.%s" % (__name__, i)
                                            for i in testmod_names]))
    return suite

