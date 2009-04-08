from bzrlib.commands import Command, register_command


class cmd_builder(Command):

    def run(self):
        self.outf.write("Patty-cake patty-cake\n")


register_command(cmd_builder)


def test_suite():
    from unittest import TestSuite
    from bzrlib.plugins.builder import tests
    result = TestSuite()
    result.addTest(tests.test_suite())
    return result
