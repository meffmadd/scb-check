class Base:
    field = 1

    def work(self):
        return self.field

    def reverse(self, client: "Client"):
        return client.run(self)


class Override(Base):
    def work(self):
        return 2


class Client:
    def run(self, value: Base):
        value.work()
        value.work()
        return value.field


class Child(Base):
    def run(self):
        self.work()
        return self.field


class TypeOnly:
    field: Base


class EmptyChild(Base):
    pass


class SelfOnly:
    field = 1

    def work(self):
        self.work()
        return self.field


class AttrsOnly:
    def inspect(self, value: Base):
        return value.field
