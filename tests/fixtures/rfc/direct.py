"""Hand-worked direct response counts: 1, 2, 3, 3, 2, 2, 0."""


class Leaf:
    def finish(self):
        return 1


class Middle:
    def work(self, leaf: Leaf):
        return leaf.finish()


class Base:
    def run(self, other: Middle, leaf: Leaf):
        other.work(leaf)
        other.work(leaf)
        return Base.run(self, other, leaf)

    def stay(self):
        return 1


class Child(Base):
    def stay(self):
        return 2


class Override(Base):
    def run(self, other: Middle, leaf: Leaf):
        return 3


class Isolated:
    def first(self):
        return 1

    def second(self):
        ...


class Empty:
    pass
