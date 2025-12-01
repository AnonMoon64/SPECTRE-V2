# plugins/refresh.py
from .base_plugin import BasePlugin

# Plugin metadata for loader
plugin_info = {
    'name': 'Refresh',
    'priority': 2,
    'handled_types': []
}


class RefreshPlugin(BasePlugin):
    def __init__(self, parent):
        super().__init__(parent)
        self.name = "Refresh"
        self.menu_action = self.name
        self.category = "Bot"
        self.priority = 2

    def execute(self, target):
        try:
            # Clear the current device model and reload JSON
            # Use the DeviceTableModel API (no shim fallback required)
            self.parent.device_model.clear()
            self.parent.device_status.clear()
            # Reload the JSON file into the model
            self.parent.load_connections()
            self.parent.log_buffered("Refreshed bot list from JSON")
        except Exception as e:
            self.parent.log_buffered(f"Error refreshing bot list: {e}")