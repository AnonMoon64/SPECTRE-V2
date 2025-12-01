#!/usr/bin/env python3
"""Shim that delegates to the example implementation located in `examples/`.

This file remains in `plugins/bin/` to allow discovery by the loader when
contributors build the example locally and prefer running the script in-place.
"""
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
EXAMPLE_SCRIPT = os.path.join(REPO_ROOT, 'examples', 'screenshot_plugin.py')

if os.path.exists(EXAMPLE_SCRIPT):
    # Run the example script directly
    os.execv(sys.executable, [sys.executable, EXAMPLE_SCRIPT] + sys.argv[1:])
else:
    # No example found — print an explanatory message and exit non-zero
    print('{"error": "screenshot example script not found; build a binary or place the script in examples/"}')
    sys.exit(1)
