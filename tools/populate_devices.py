"""Sanity harness: populate DeviceTableModel with many devices and measure timings.

Run this script from the workspace root. It creates a QApplication (required by Qt
models), constructs a DeviceTableModel, inserts N devices, then updates them.
"""
import time
import sys
from PyQt6.QtWidgets import QApplication
from core.device_model import DeviceTableModel


def run(n=10000):
    app = QApplication([])
    model = DeviceTableModel()

    devices = []
    for i in range(n):
        ip = f"192.168.{i // 256}.{i % 256}"
        bot_id = f"bot-{i}"
        target = f"{ip}:{bot_id}"
        devices.append({
            'id': bot_id,
            'ip': ip,
            'hostname': f"host-{i}",
            'os': 'Windows',
            'status': 'Disconnected',
            'last_ping': 'N/A',
            'target': target,
        })

    t0 = time.time()
    model.load_devices(devices)
    t1 = time.time()
    print(f"Loaded {n} devices into model in {t1 - t0:.3f} seconds")

    # Update half of them
    t0 = time.time()
    for i in range(0, n, 2):
        ip = devices[i]['ip']
        bot_id = devices[i]['id']
        target = devices[i]['target']
        model.update_or_insert({'target': target, 'status': 'Connected', 'last_ping': '0 sec ago'})
    t1 = time.time()
    print(f"Updated {n//2} devices in {t1 - t0:.3f} seconds")

    # Basic checks
    print('Row count:', model.rowCount())
    # Clean up
    app.quit()


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('-n', type=int, default=10000)
    args = p.parse_args()
    run(args.n)
