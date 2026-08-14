#!/usr/bin/env python3
"""Direct validation script for xiaopai_publish node"""
import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

print("Validating xiaopai_publish node...")
print(f"Project root: {project_root}")

# 1. Check step file syntax
print("\n1. Checking step file syntax...")
try:
    import py_compile
    py_compile.compile(os.path.join(project_root, 'backend/steps/s_xiaopai_publish.py'), doraise=True)
    print("   ✓ Step file syntax is valid")
except py_compile.PyCompileError as e:
    print(f"   ✗ Syntax error: {e}")
    sys.exit(1)

# 2. Check step class import
print("\n2. Checking step class import...")
try:
    from backend.steps.s_xiaopai_publish import S_XiaopaiPublish
    print("   ✓ Step class can be imported")
    
    # Check step attributes
    step = S_XiaopaiPublish()
    print(f"   ✓ Step ID: {step.step_id}")
    print(f"   ✓ Step name: {step.step_name}")
    
except ImportError as e:
    print(f"   ✗ Import error: {e}")
    sys.exit(1)

# 3. Check step registry
print("\n3. Checking step registry...")
try:
    from backend.steps.step_registry import get_step_instance
    step = get_step_instance("xiaopai_publish")
    if step:
        print("   ✓ Step is registered with id 'xiaopai_publish'")
    else:
        print("   ✗ Step is NOT registered with id 'xiaopai_publish'")
        sys.exit(1)
        
    step_s = get_step_instance("s_xiaopai_publish")
    if step_s:
        print("   ✓ Step is registered with id 's_xiaopai_publish'")
    else:
        print("   ✗ Step is NOT registered with id 's_xiaopai_publish'")
        sys.exit(1)
        
except ImportError as e:
    print(f"   ✗ Import error: {e}")
    sys.exit(1)

# 4. Check node type definition
print("\n4. Checking node type definition...")
try:
    from backend.config.builtin_node_types import get_builtin_node_type
    node_type = get_builtin_node_type("xiaopai_publish")
    if node_type:
        print("   ✓ Node type is defined in builtin_node_types")
        print(f"   ✓ Name: {node_type.get('name')}")
        print(f"   ✓ Category: {node_type.get('category')}")
        print(f"   ✓ Execution domain: {node_type.get('execution_domain')}")
        
        # Check inputs and outputs
        inputs = node_type.get('inputs', [])
        outputs = node_type.get('outputs', [])
        print(f"   ✓ Inputs: {len(inputs)} ports")
        print(f"   ✓ Outputs: {len(outputs)} ports")
        
        # Check config fields
        config_fields = node_type.get('configFields', [])
        print(f"   ✓ Config fields: {len(config_fields)} fields")
    else:
        print("   ✗ Node type is NOT defined in builtin_node_types")
        sys.exit(1)
        
except ImportError as e:
    print(f"   ✗ Import error: {e}")
    sys.exit(1)

# 5. Check frontend fallback
print("\n5. Checking frontend fallback...")
try:
    # Read the fallback file and check for node definition
    fallback_path = os.path.join(project_root, 'frontend/src/lib/fallbackNodeTypes.ts')
    if os.path.exists(fallback_path):
        with open(fallback_path, 'r', encoding='utf-8') as f:
            content = f.read()
            if '"xiaopai_publish"' in content:
                print("   ✓ Node is defined in frontend fallback")
            else:
                print("   ✗ Node is NOT defined in frontend fallback")
                sys.exit(1)
    else:
        print("   ⚠ Frontend fallback file not found (this is OK during development)")
except Exception as e:
    print(f"   ⚠ Could not check frontend fallback: {e}")

print("\n" + "="*50)
print("✓ All validations passed!")
print("="*50)
print("\nNode 'xiaopai_publish' is ready for use!")
print("You can now:")
print("1. Restart the backend server")
print("2. The node will appear in the workflow editor under 'publish' category")
print("3. Add it to your workflow and configure it")