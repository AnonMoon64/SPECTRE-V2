# SPECTRE Developer Guide (Plugin API & Migration)

This document describes the updated plugin API, loader expectations, and steps
to migrate existing plugins to the new metadata-driven system.

Plugin discovery
- Modules inside `plugins/` (except `__init__.py` and `base_plugin.py`) are
  discovered by `plugins.loader.load_plugins(parent)`.
- A plugin module may expose one of the following entry points (in order of
  preference):
  - `plugin_entry(parent)` : factory function that returns a plugin instance
  - `Plugin` : a class which will be instantiated with `parent`
  - legacy class named `<ModuleNameCapitalized>Plugin` (shim for backward compatibility)

Metadata
- A module may provide `plugin_info` dict at module scope. Example:

```python
plugin_info = {
    'name': 'Send Message',
    'priority': 60,
    'handled_types': ['message_response'],
}
```

- `handled_types` informs the `core.router.Router` which message `type` values
  the plugin wants to receive. If `handled_types` is empty or missing, the
  plugin is treated as a broadcast listener receiving all messages (legacy
  behavior).

BasePlugin
- Plugins should subclass `plugins.base_plugin.BasePlugin` and implement at
  least:
  - `execute(target)` : called by the GUI when user triggers the plugin
  - `handle_response(data)` : handle inbound messages (keep this lightweight)

- Optional lifecycle hooks:
  - `activate()` : called after the plugin is loaded
  - `deactivate()` : called at shutdown

Transport
- Use `parent.transport.send_command(command_dict, encrypt=True)` instead of
  accessing `parent.client.publish` directly. The transport centralizes
  encryption, topic handling, and will queue messages when disconnected.

Workers
- Long-running or blocking operations should use `core.workers.submit_task(fn, *args)`
  to avoid blocking the GUI thread.

Migration checklist
1. Add `plugin_info` metadata with `name`, `priority`, and `handled_types`.
2. Replace direct `parent.client.publish(...)` calls with
   `parent.transport.send_command(...)`.
3. If the plugin performs blocking I/O or heavy computation, offload it with
   `core.workers.submit_task` and update GUI via signals/slots.
4. Optionally implement `activate()` for initialization work.

Example plugin template

```python
from .base_plugin import BasePlugin

plugin_info = {
    'name': 'Example',
    'priority': 10,
    'handled_types': ['example_response']
}

class Plugin(BasePlugin):
    def __init__(self, parent):
        super().__init__(parent)
        self.name = 'Example'

    def activate(self):
        # setup subscriptions or state
        pass

    def execute(self, target):
        cmd = {'type': 'command', 'target': target, 'action': 'do_example'}
        self.parent.transport.send_command(cmd)

    def handle_response(self, data):
        # lightweight handler
        pass
```

If you need help migrating a plugin, I can provide a patch for that plugin.
