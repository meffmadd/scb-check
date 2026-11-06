"""Client file document."""
from domain.model import Model, Payload

class Client:
    def invoke(self, model: Model):
        model.run(None)
        model.run(None)
    def inspect(self, payload: Payload): return payload.size

def caller(model: Model): return model.run(None)

Model.run(None, None)
