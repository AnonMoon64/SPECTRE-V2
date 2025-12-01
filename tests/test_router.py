import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.router import Router


class DummyPlugin:
    def __init__(self, name, handled_types=None):
        self.name = name
        self.handled_types = handled_types or []
        self.received = []

    def handle_response(self, data):
        self.received.append(data)


def test_router_dispatches_by_type_and_broadcast():
    p1 = DummyPlugin('p1', handled_types=['foo'])
    p2 = DummyPlugin('p2', handled_types=[])  # broadcast listener
    router = Router([p1, p2])

    msg = {'type': 'foo', 'value': 1}
    router.dispatch(msg)
    assert len(p1.received) == 1
    assert p1.received[0]['value'] == 1
    assert len(p2.received) == 1

    # non-matching type should still go to broadcast listener
    p1.received.clear()
    p2.received.clear()
    router.dispatch({'type': 'bar', 'value': 2})
    assert len(p1.received) == 0
    assert len(p2.received) == 1
