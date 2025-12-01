# plugins/base_plugin.py
"""Base plugin API.

This defines a lightweight BasePlugin with a small metadata contract. Existing
plugins that subclass the previous BasePlugin will remain compatible.
"""
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BasePlugin:
    """Minimal plugin base class.

    Attributes:
        parent: reference to the GUI/core object passed at load time.
        name: human-friendly plugin name.
        menu_action: label used in menus.
        priority: integer priority for sorting (higher runs first).
        handled_types: list of message `type` strings this plugin wants to receive.
        plugin_info: optional dict provided by module to describe metadata.
    """

    def __init__(self, parent):
        self.parent = parent
        self.name = "Base Plugin"
        self.menu_action = self.name
        self.priority = 0
        self.handled_types = []
        self.plugin_info = {'name': self.name}
        logger.info(f"BasePlugin initialized: name={self.name}, priority={self.priority}")

    # Lifecycle hooks
    def activate(self):
        """Called once after the plugin is loaded. Plugins may use this to
        register dynamic handlers or setup resources."""
        return None

    def deactivate(self):
        """Called when plugin is unloaded/shutdown."""
        return None

    # Backwards-compatible API expected by current GUI
    def execute(self, target):
        raise NotImplementedError("execute method must be implemented by subclasses")

    def handle_response(self, data):
        """Handle an inbound message from the core. Default implementation
        is a no-op. New plugins should declare `handled_types` so the router
        can dispatch only relevant messages."""
        return None

    def get_menu_action(self):
        return self.menu_action
