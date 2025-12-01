import os
import sys
import importlib
import logging
import json
import subprocess
import tempfile
import shutil
from types import SimpleNamespace

logger = logging.getLogger(__name__)

EXCLUDE = {'__init__.py', 'base_plugin.py'}


def load_plugins(parent):
    plugins = []
    plugin_dir = os.path.dirname(__file__)
    try:
        files = os.listdir(plugin_dir)
    except Exception as e:
        logger.error(f"Failed to list plugins directory: {e}")
        return plugins

    for filename in files:
        if not filename.endswith('.py') or filename in EXCLUDE:
            continue
        module_name = filename[:-3]
        try:
            module = importlib.import_module(f'plugins.{module_name}')
        except Exception as e:
            logger.error(f"Failed to import plugin module {module_name}: {e}")
            continue

        # Prefer explicit module-level metadata and entry points
        try:
            plugin_instance = None

            # Module can expose `plugin_entry(parent)` factory
            if hasattr(module, 'plugin_entry') and callable(module.plugin_entry):
                try:
                    plugin_instance = module.plugin_entry(parent)
                except Exception as e:
                    logger.error(f"Error creating plugin via plugin_entry in {module_name}: {e}")

            # Module can expose `Plugin` class
            if plugin_instance is None and hasattr(module, 'Plugin'):
                try:
                    plugin_cls = getattr(module, 'Plugin')
                    plugin_instance = plugin_cls(parent)
                except Exception as e:
                    logger.error(f"Error instantiating Plugin class in {module_name}: {e}")

            # Backwards-compat: old convention <ModuleNameCapitalized>Plugin
            if plugin_instance is None:
                class_name_parts = module_name.split('_')
                plugin_class_name = ''.join(part.capitalize() for part in class_name_parts) + 'Plugin'
                plugin_cls = getattr(module, plugin_class_name, None)
                if plugin_cls:
                    try:
                        plugin_instance = plugin_cls(parent)
                    except Exception as e:
                        logger.error(f"Error instantiating legacy plugin class {plugin_class_name} in {module_name}: {e}")

            if plugin_instance is None:
                logger.error(f"No plugin entry point found in module {module_name}; expected plugin_entry, Plugin, or {plugin_class_name}")
                continue

            # If module provides plugin_info dict, apply it to instance for metadata
            info = getattr(module, 'plugin_info', None)
            if isinstance(info, dict):
                try:
                    for k, v in info.items():
                        setattr(plugin_instance, k, v)
                except Exception:
                    logger.debug(f"Failed to set plugin_info attributes for {module_name}")

            # Ensure sensible defaults
            if not hasattr(plugin_instance, 'name'):
                plugin_instance.name = getattr(plugin_instance, 'menu_action', module_name)
            if not hasattr(plugin_instance, 'priority'):
                plugin_instance.priority = getattr(plugin_instance, 'priority', 0)
            if not hasattr(plugin_instance, 'handled_types'):
                plugin_instance.handled_types = getattr(plugin_instance, 'handled_types', [])

            plugins.append(plugin_instance)
            logger.info(f"Loaded plugin: {plugin_instance.name} (module={module_name}) priority={plugin_instance.priority}")

        except Exception as e:
            logger.error(f"Unexpected error loading plugin {module_name}: {e}")

    # Also discover any external binary plugins and append them
    try:
        ext = _discover_external_binaries(parent)
        plugins.extend(ext)
    except Exception:
        logger.debug("No external binaries discovered or error during discovery")

    try:
        sorted_plugins = sorted(plugins, key=lambda p: getattr(p, 'priority', 0), reverse=True)
        return sorted_plugins
    except Exception as e:
        logger.error(f"Error sorting plugins: {e}")
        return plugins


def _discover_external_binaries(parent):
    """Discover executable plugins under `plugins/bin/` or top-level exe files.

    An external plugin is represented by an executable file (e.g. .exe) and an
    optional JSON metadata file with the same base name. The metadata should
    contain at least `name` and may contain `priority` and `handled_types`.
    """
    ext_plugins = []
    plugin_dir = os.path.dirname(__file__)
    bin_dir = os.path.join(plugin_dir, 'bin')
    search_dirs = [plugin_dir, bin_dir]
    exts = {'.exe', '.bat', '.cmd'}

    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        try:
            # Collect files by base name so we can prefer .exe over .bat/.cmd to avoid duplicates
            by_base = {}
            for fn in os.listdir(d):
                path = os.path.join(d, fn)
                if not os.path.isfile(path):
                    continue
                base, ext = os.path.splitext(fn)
                if ext.lower() not in exts:
                    continue
                # Preference order: .exe > .bat > .cmd
                priority = 0
                if ext.lower() == '.exe':
                    priority = 3
                elif ext.lower() == '.bat':
                    priority = 2
                elif ext.lower() == '.cmd':
                    priority = 1

                entry = by_base.get(base)
                if entry is None or priority > entry['priority']:
                    by_base[base] = {'filename': fn, 'path': path, 'ext': ext, 'priority': priority}

            for base, info in by_base.items():
                fn = info['filename']
                path = info['path']
                ext = info['ext']

                meta = {}
                meta_file = os.path.join(d, base + '.json')
                if os.path.exists(meta_file):
                    try:
                        with open(meta_file, 'r') as f:
                            meta = json.load(f)
                    except Exception:
                        logger.debug(f"Failed to read metadata for external plugin {fn}")

                # Create a lightweight plugin object that wraps executing the binary
                class ExternalBinaryPlugin:
                    def __init__(self, parent, path, meta, filename, ext):
                        self.parent = parent
                        self.path = path
                        self.filename = filename
                        self.ext = ext
                        self.name = meta.get('name', filename)
                        self.priority = meta.get('priority', 0)
                        self.handled_types = meta.get('handled_types', [])
                        self.menu_action = meta.get('menu_action', self.name)
                        self.category = meta.get('category', 'External')

                    def get_menu_action(self):
                        return self.menu_action

                    def _resolve_executable(self):
                        # Prefer the original path if present
                        if os.path.exists(self.path):
                            return self.path

                        if getattr(sys, 'frozen', False):
                            meipass = getattr(sys, '_MEIPASS', None)
                            if meipass:
                                try:
                                    base_pkg_dir = os.path.dirname(__file__)
                                    rel = os.path.relpath(self.path, start=base_pkg_dir)
                                except Exception:
                                    rel = os.path.basename(self.path)
                                candidate = os.path.join(meipass, rel)
                                if os.path.exists(candidate):
                                    return candidate

                        found = shutil.which(self.filename)
                        if found:
                            return found

                        return self.path

                    def _log_process_output(self, proc):
                        # Read stdout/stderr asynchronously and forward to GUI log
                        def _reader(stream, kind):
                            try:
                                for line in iter(stream.readline, b''):
                                    try:
                                        text = line.decode('utf-8', errors='replace').rstrip()
                                        self.parent.log_buffered(f"[{self.name}][{kind}] {text}")
                                    except Exception:
                                        pass
                            except Exception:
                                pass

                        import threading
                        if proc.stdout:
                            t_out = threading.Thread(target=_reader, args=(proc.stdout, 'stdout'), daemon=True)
                            t_out.start()
                        if proc.stderr:
                            t_err = threading.Thread(target=_reader, args=(proc.stderr, 'stderr'), daemon=True)
                            t_err.start()

                    def execute(self, target):
                        try:
                            # First, instruct the server/bot by sending a command through the parent's transport
                            try:
                                cmd_msg = {'type': 'command', 'target': target, 'action': 'screenshot'}
                                transport = getattr(self.parent, 'transport', None)
                                if transport is not None:
                                    try:
                                        # try encrypt flag if supported
                                        transport.send_command(cmd_msg, encrypt=True)
                                    except TypeError:
                                        transport.send_command(cmd_msg)
                                    try:
                                        self.parent.log_buffered(f"External plugin wrapper sent command to server for {target}")
                                    except Exception:
                                        pass
                                else:
                                    try:
                                        self.parent.log_buffered(f"External plugin wrapper: no transport available to send command for {target}")
                                    except Exception:
                                        pass
                            except Exception as e:
                                try:
                                    self.parent.log_buffered(f"External plugin wrapper failed to send command: {e}")
                                except Exception:
                                    pass

                            exe_path = self._resolve_executable()

                            # Construct command
                            if os.name == 'nt' and self.ext.lower() in ('.bat', '.cmd'):
                                cmd = ['cmd.exe', '/c', exe_path, str(target)]
                            else:
                                cmd = [exe_path, str(target)]

                            # Start process capturing output
                            exe_cwd = os.path.dirname(exe_path) if exe_path else None
                            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=exe_cwd, shell=False)
                            try:
                                self.parent.log_buffered(f"Launched external plugin {self.name} (pid={getattr(proc, 'pid', 'n/a')}) for {target} [exe={exe_path} exists={os.path.exists(exe_path)} cwd={exe_cwd}]")
                            except Exception:
                                pass
                            # Read output asynchronously
                            try:
                                self._log_process_output(proc)
                            except Exception:
                                pass
                            # Monitor process exit in background and log exit code
                            try:
                                import threading
                                def _wait_and_log(p):
                                    try:
                                        rc = p.wait()
                                        try:
                                            self.parent.log_buffered(f"External plugin {self.name} exited with code {rc}")
                                        except Exception:
                                            pass
                                    except Exception:
                                        pass
                                t_mon = threading.Thread(target=_wait_and_log, args=(proc,), daemon=True)
                                t_mon.start()
                            except Exception:
                                pass
                        except Exception as e:
                            try:
                                self.parent.log_buffered(f"Failed to launch external plugin {self.name}: {e}")
                            except Exception:
                                pass

                    def handle_response(self, data):
                        return

                    def deactivate(self):
                        return

                try:
                    inst = ExternalBinaryPlugin(parent, path, meta, fn, ext)
                    ext_plugins.append(inst)
                    logger.info(f"Loaded external plugin: {inst.name} (path={path})")
                except Exception as e:
                    logger.error(f"Error creating external plugin wrapper for {path}: {e}")
        except Exception:
            continue

    return ext_plugins
