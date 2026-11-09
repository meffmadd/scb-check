"""Known method RIC: 48 pairs, ratio total 4.5, mean 0.09375, max 1.5."""


class Owner:
    def target(self):
        return 1

    def zero_owner(self):
        ...

    def unused(self):
        return 0

    def first(self):
        return self.target() + self.target()

    def second(self):
        return self.target()

    def recur(self):
        return self.recur()


class Client:
    def first(self, value: Owner):
        value.target()
        value.target()
        value.zero_owner()
        value.zero_owner()
        return value.recur()

    def second(self, value: Owner):
        return value.target()

    def third(self, value: Owner):
        return value.target()


class Other:
    def one(self, value: Owner, unknown):
        unknown.unused()
        value.unused

        def nested():
            return value.zero_owner()

        return value.target()


class Child(Owner):
    def run(self):
        return self.target()


class Override(Owner):
    def target(self):
        return 2


def free(value: Owner):
    return value.zero_owner()
