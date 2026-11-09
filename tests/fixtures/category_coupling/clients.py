from targets import Primary, Secondary
from other import Utility


class FirstClient:
    def run(self, first: Primary, second: Secondary, utility: Utility):
        first.work()
        first.work()
        second.work()
        return utility.work()


class SecondClient:
    def run(self, target: Primary):
        return target.value


def free_client(target: Primary):
    return target.work()


Primary.work(None)
