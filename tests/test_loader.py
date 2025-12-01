import sys
import os
import types

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from plugins import loader


class DummyParent:
    def __init__(self):
        self.client = None
        self.topic = '/commands/'
        self.is_connected = False


def test_load_plugins_returns_plugins():
    parent = DummyParent()
    plugins = loader.load_plugins(parent)
    assert isinstance(plugins, list)
    # Expect Ping and Message plugins to be present by name
    names = {getattr(p, 'name', None) for p in plugins}
    assert 'Ping' in names
    assert 'Send Message' in names
