#!/usr/bin/env python3
"""Check syntax of the new step file"""
import py_compile
import sys

try:
    py_compile.compile('backend/steps/s_xiaopai_publish.py', doraise=True)
    print("✓ Step file syntax is valid")
    sys.exit(0)
except py_compile.PyCompileError as e:
    print(f"✗ Syntax error: {e}")
    sys.exit(1)