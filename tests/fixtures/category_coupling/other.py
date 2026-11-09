from targets import Primary


class Utility:
    def work(self):
        return 3


class ThirdClient:
    def run(self, target: Primary):
        return target.work()
