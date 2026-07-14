"""Streamlit Community Cloud entry point.

Keep this file at the repository root. The complete application lives in
``app.py``; executing it through ``runpy`` preserves one source of truth while
allowing Streamlit Cloud's conventional main-file name.
"""
from __future__ import annotations

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().with_name("app.py")), run_name="__main__")
