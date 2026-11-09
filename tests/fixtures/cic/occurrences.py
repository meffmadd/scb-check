class Root:
    field = 1

    def work(self):
        return self.field


class Middle(Root):
    def run(self):
        self.work()
        self.work()
        self.field += 1
        return self.work


class Leaf(Middle):
    selected = Root.work

    def work(self):
        return 2

    def run(self, unknown):
        self.work()
        self.field
        Root.work(self)
        Unrelated.work(self)
        unknown.work()

        def nested():
            return Root.work

        return nested


class EmptyLeaf(Leaf):
    pass


class Unrelated:
    def work(self):
        return 3


class DeclarationOnly(Root):
    pass
