#!/usr/bin/env python3
"""Validate syntax of the new step file using ast"""
import ast
import sys

try:
    with open('backend/steps/s_xiaopai_publish.py', 'r', encoding='utf-8') as f:
        source = f.read()
    
    # Parse the source code
    ast.parse(source)
    print("✓ Step file syntax is valid (AST parsing successful)")
    sys.exit(0)
except SyntaxError as e:
    print(f"✗ Syntax error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)