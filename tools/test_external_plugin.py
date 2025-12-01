import sys
sys.path.insert(0, '.')
from plugins.loader import load_plugins
import time

class Dummy:
    def __init__(self):
        # simple logger used by external plugin wrapper
        self._logs = []
    def log_buffered(self, msg):
        print('DUMMY LOG:', msg)
        self._logs.append(msg)

if __name__ == '__main__':
    p = Dummy()
    plugins = load_plugins(p)
    # Find external plugin by category or name
    ext = None
    for pl in plugins:
        name = getattr(pl, 'name', '')
        if name and ('External' in getattr(pl,'category','') or 'Echo' in name):
            ext = pl
            break
    if not ext:
        print('No external plugin found')
        sys.exit(1)
    print('Found external plugin:', ext.name, 'path=', getattr(ext,'path',None))
    # Execute for a sample target
    target = '127.0.0.1:bot-test'
    ext.execute(target)
    # Wait a moment for the batch file to write
    time.sleep(0.2)
    out_file = None
    try:
        base = getattr(ext,'path')
        import os
        out_file = os.path.join(os.path.dirname(base), 'echo_out.txt')
        if os.path.exists(out_file):
            with open(out_file, 'r') as f:
                print('External plugin output (last 5 lines):')
                lines = f.read().strip().splitlines()
                for L in lines[-5:]:
                    print(L)
        else:
            print('No output file found at', out_file)
    except Exception as e:
        print('Error reading output file:', e)
