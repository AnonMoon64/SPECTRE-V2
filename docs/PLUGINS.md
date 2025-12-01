External Binary Plugins (How-to)
================================

Purpose
-------
SPECTRE supports "external binary" plugins: executables or scripts placed under `plugins/` or `plugins/bin/`. These are discovered at runtime and wrapped by a lightweight adapter so users can add tools written in any language.

Discovery & metadata
--------------------
- Any file under `plugins/` or `plugins/bin/` whose extension is one of `.exe`, `.bat`, `.cmd`, or any executable script will be considered.
- An optional metadata file with the same base name and a `.json` extension can be provided. Example: `plugins/bin/screenshot_plugin.exe` and `plugins/bin/screenshot_plugin.json`.
- Metadata keys:
  - `name` (string): human-friendly name shown in menus.
  - `priority` (int): plugin ordering; higher runs first.
  - `handled_types` (list): message types the plugin handles (for in-process plugins). External binaries do not receive in-process responses by default.
  - `category` (string): plugin category for menus (default: `External`).

Interface contract for external binaries
----------------------------------------
- Invocation: The external program is called with a single positional argument `target` which is the `ip:botid` string (or `all` in broadcast cases).
  Example: `screenshot_plugin.exe 127.0.0.1:bot-123`
- Output: External plugins can communicate results through any out-of-band mechanism. Common patterns:
  - Write output files under `plugins/bin/` (e.g. `screenshots/`) and print a short JSON line to stdout with a path: `{ "out": "plugins/bin/screenshots/.." }`.
  - Send results back via the MQTT broker (advanced).
- Exit codes: 0 = success, non-zero = failure. Plugins may print JSON error messages to stdout/stderr.

Packaging external plugins
-------------------------
- You can implement a plugin as a script (`.py`) and convert it to a standalone binary using PyInstaller:

  ```powershell
  pyinstaller --onefile --add-data "plugins/bin;plugins/bin" plugins/bin/screenshot_plugin.py
  ```

- When packaging SPECTRE itself with PyInstaller, include your `plugins/bin` directory as a `datas` entry in the spec or ensure it's placed next to the built exe.

Example: `plugins/bin/screenshot_plugin.py`
------------------------------------------
- A cross-platform Python example is included in the repository. It prefers the `mss` package (pure-python) for speed and falls back to common platform utilities (`screencapture`, `scrot`, `import`, or PowerShell) when `mss` is not present.
- The script saves results under `plugins/bin/screenshots/` and prints a JSON line on success.

Best practices for binary plugins
--------------------------------
- Keep the interface simple: accept a target argument and return a short success message or a file path.
- Avoid blocking the SPECTRE main process: external plugins run in their own process boundary.
- Clean up temporary files if you extract embedded resources at runtime.
- For high-performance native code (e.g., optimized screenshot capture), implement platform-specific code paths and provide a small shim for uniform invocation.

Troubleshooting
---------------
- If SPECTRE cannot find your plugin in a frozen build, ensure the plugin binary/data is included in the PyInstaller `datas` entries and that the loader handles `sys._MEIPASS`. The loader in this repo already attempts `_MEIPASS` and `shutil.which()` fallbacks.
- For permission errors, check that the plugin file is executable and not blocked by antivirus.

