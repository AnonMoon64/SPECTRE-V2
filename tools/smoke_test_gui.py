# Headless smoke test for SPECTRE GUI core logic.
# Creates a QApplication and RatGui instance, triggers a few operations
# (load_settings, load_connections, presence tick, flush_ui_updates) and exits.
import sys
import time
sys.path.insert(0, '.')
from PyQt6.QtWidgets import QApplication
from SPECTRE import RatGui

def run_smoke():
    app = QApplication(sys.argv)
    gui = RatGui()
    # Do not show the window; just interact with core methods
    gui.load_settings()
    gui.load_connections()
    # toggle presence verbose for the test
    gui.presence_verbose = True
    # simulate a presence tick
    gui._presence_tick()
    # simulate queued device updates (if any)
    gui.flush_ui_updates()
    # call update_device_status to ensure no exceptions
    gui.update_device_status()
    # quick log
    gui.log_buffered('Smoke test completed successfully')
    # flush logs to ensure message is visible
    gui.flush_ui_updates()
    # cleanup
    try:
        gui.close()
    except Exception:
        pass
    app.quit()

if __name__ == '__main__':
    run_smoke()
    print('Smoke test finished')
