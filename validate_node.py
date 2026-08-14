import py_compile
import sys

try:
    py_compile.compile('backend/steps/s_xiaopai_publish.py', doraise=True)
    print("✓ Step file syntax is valid")
except py_compile.PyCompileError as e:
    print(f"✗ Syntax error: {e}")
    sys.exit(1)

# Check if step can be imported
try:
    sys.path.insert(0, '.')
    from backend.steps.s_xiaopai_publish import S_XiaopaiPublish
    print("✓ Step class can be imported")
    
    # Check if step is registered
    from backend.steps.step_registry import get_step_instance
    step = get_step_instance("xiaopai_publish")
    if step:
        print("✓ Step is registered in step_registry")
    else:
        print("✗ Step is NOT registered in step_registry")
        sys.exit(1)
        
    # Check node type definition
    from backend.config.builtin_node_types import get_builtin_node_type
    node_type = get_builtin_node_type("xiaopai_publish")
    if node_type:
        print("✓ Node type is defined in builtin_node_types")
    else:
        print("✗ Node type is NOT defined in builtin_node_types")
        sys.exit(1)
        
except ImportError as e:
    print(f"✗ Import error: {e}")
    sys.exit(1)

print("\n✓ All validations passed!")