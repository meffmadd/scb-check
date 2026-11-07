"""Eleven classes with partial MPC counts summing to seven physical call sites."""


class Target:
    def ping(self):
        return 1

    def other(self):
        return 2


class Override(Target):
    def ping(self):
        return 3


class Caller:
    def run(self, other: Target):
        other.ping()
        other.ping()
        for _ in (1, 2, 3):
            other.other()
        self.own()
        Target()
        return Target.ping

    def own(self):
        return 0


class Ancestor:
    def inherited(self):
        return Target.ping()


class Child(Ancestor):
    def run(self):
        return self.inherited()


class EmptyChild(Ancestor):
    pass


class SelfOnly:
    def work(self):
        return self.work()


class Contract:
    def work(self): ...


class ContractClient:
    def run(self, value: Contract):
        return value.work()


class IgnoredBodies:
    initial = Target.ping()

    def run(self):
        callback = lambda: Target.ping()

        def nested():
            return Target.ping()

        return callback, nested


class StaticSource:
    @staticmethod
    def run():
        return Target.ping()

    @classmethod
    def run_other(cls):
        return Target.other()


def outside():
    return Target.ping()
