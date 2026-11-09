class Primary:
    value = 1

    def work(self):
        return self.value


class Secondary:
    def work(self):
        return 2


class InternalClient:
    def run(self, target: Primary):
        return target.work()
