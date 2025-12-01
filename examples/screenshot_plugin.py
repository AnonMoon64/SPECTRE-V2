#!/usr/bin/env python3
"""
Example source for `screenshot_plugin` (moved from plugins/bin).
This is the original Python implementation kept under `examples/` for contributors
who want to inspect and build the plugin themselves.

To build a binary with PyInstaller (Windows example):
    & "C:/Program Files/Python313/python.exe" -m PyInstaller --onefile --distpath plugins\bin\dist --workpath build\screenshot_build plugins\bin\screenshot_plugin.py

After building, copy/move the produced exe to `plugins/bin/` so SPECTRE discovers it.
"""

# The script content below is unchanged from the plugin example moved here for easy editing.
import sys
import os
import json
import hashlib

OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'plugins', 'bin', 'screenshots')
OUT_DIR = os.path.abspath(OUT_DIR)
os.makedirs(OUT_DIR, exist_ok=True)


def sanitize_target(target_str: str) -> str:
    h = hashlib.sha1(target_str.encode('utf-8')).hexdigest()[:12]
    return f"screenshot_{h}.png"


def try_mss(path: str) -> bool:
    try:
        import mss
        import mss.tools
        with mss.mss() as sct:
            monitor = sct.monitors[0]
            img = sct.grab(monitor)
            mss.tools.to_png(img.rgb, img.size, output=path)
        return True
    except Exception:
        return False


def try_platform_tools(path: str) -> bool:
    import subprocess
    import platform
    system = platform.system()
    if system == 'Darwin':
        try:
            subprocess.check_call(['screencapture', '-x', path])
            return True
        except Exception:
            return False
    elif system == 'Linux':
        try:
            subprocess.check_call(['scrot', path])
            return True
        except Exception:
            pass
        try:
            subprocess.check_call(['import', '-window', 'root', path])
            return True
        except Exception:
            return False
    elif system == 'Windows':
        ps_script = (
            "Add-Type -AssemblyName System.Drawing;"
            "$bmp = New-Object System.Drawing.Bitmap([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width, [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height);"
            "$graphics = [System.Drawing.Graphics]::FromImage($bmp);"
            "$graphics.CopyFromScreen([System.Drawing.Point]::Empty, [System.Drawing.Point]::Empty, $bmp.Size);"
            f"$bmp.Save(\"{path}\", [System.Drawing.Imaging.ImageFormat]::Png)"
        )
        try:
            subprocess.check_call(['powershell', '-NoProfile', '-Command', ps_script])
            return True
        except Exception:
            return False
    else:
        return False


def main():
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'missing target arg'}))
        sys.exit(2)

    target = sys.argv[1]
    fname = sanitize_target(target)
    outpath = os.path.join(OUT_DIR, fname)

    ok = False
    ok = try_mss(outpath)
    if not ok:
        ok = try_platform_tools(outpath)

    if not ok:
        print(json.dumps({'error': 'screenshot failed'}))
        sys.exit(1)

    print(json.dumps({'out': outpath}))
    sys.stdout.flush()


if __name__ == '__main__':
    main()
