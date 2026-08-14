#!/usr/bin/env python3
"""Validate syntax of the new step file using compile"""
import sys

try:
    with open('backend/steps/s_xiaopai_publish.py', 'r', encoding='utf-8') as f:
        source = f.read()
    
    # Compile the source code
    compile(source, 'backend/steps/s_xiaopai_publish.py', 'exec')
    print("✓ Step file syntax is valid (compile successful)")
    sys.exit(0)
except SyntaxError as e:
    print(f"✗ Syntax error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)