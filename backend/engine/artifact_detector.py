"""
Artifact detector: checks if step output artifacts exist on disk.
"""
import os


def check_step_artifacts(task_dir: str, artifacts: list) -> bool:
    """Check if all artifacts for a step exist."""
    if not artifacts:
        return False
    for artifact in artifacts:
        path = os.path.join(task_dir, artifact)
        if not os.path.exists(path):
            return False
        # Non-empty file check
        if os.path.isfile(path) and os.path.getsize(path) == 0:
            return False
    return True


def check_step_inputs(task_dir: str, input_artifacts: list) -> bool:
    """Check if all input artifacts exist."""
    return all(os.path.exists(os.path.join(task_dir, a)) for a in input_artifacts)


def clear_artifacts(task_dir: str, artifacts: list):
    """Remove step artifacts."""
    import shutil
    for artifact in artifacts:
        path = os.path.join(task_dir, artifact)
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
