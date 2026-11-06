"""Model file document."""
from typing import Self

class Payload:
    """Payload class document."""
    size: int
    def send(self):
        """Send method document."""
        return 1

class Base:
    inherited: Payload
    def work(self): return self.inherited.send()

class Model(Base):
    first: Payload
    second: Payload
    recursive: Self
    ancestor: Base
    wrapped: list[Payload]
    primitive: int
    unknown: Missing
    def own(self): return self.own()
    def run(self, payload: Payload):
        # Run comment document.
        payload.send()
        payload.send()
        self.work()
        self.own()
        return payload.size
    def nested(self):
        def inner():
            """Inner document."""
            return 1
        return inner()
