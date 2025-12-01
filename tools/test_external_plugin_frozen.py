"""
Simple integration test for external plugins.
It lists discovered external plugins (via `plugins.loader.load_plugins`) and attempts to execute them with a test target.

This does not fully emulate a frozen environment, but it exercises discovery and execution paths.

Run:
    python tools/test_external_plugin_frozen.py
"""
import plugins.loader as loader
import time

class ParentStub:
    def log_buffered(self, msg):
        print("LOG:", msg)

if __name__ == '__main__':
    parent = ParentStub()
    print("Loading plugins...")
    plugins = loader.load_plugins(parent)
    print(f"Total plugins loaded: {len(plugins)}")
    ext = [p for p in plugins if getattr(p, 'category', None) == 'External']
    print(f"External plugins found: {len(ext)}")
    for p in ext:
        print(f" - {p.name} (handled_types={getattr(p, 'handled_types', [])}, path={getattr(p, 'path', 'n/a')})")

    # Try executing each external plugin with a test target
    for p in ext:
        try:
            print(f"Executing external plugin {p.name}...")
            p.execute('127.0.0.1:bot-test')
            time.sleep(0.2)
        except Exception as e:
            print(f"Execution failed: {e}")

    print("Done.")
