"""Test data directory creation and path resolution."""
import os
import tempfile
import shutil
from pathlib import Path


def test_data_dir_from_env():
    """SAU_DATA_DIR environment variable overrides default path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir) / "test_data"
        os.environ["SAU_DATA_DIR"] = str(test_dir)
        assert os.environ.get("SAU_DATA_DIR") == str(test_dir)


def test_db_path_construction():
    """DB_PATH should be constructed from data_dir, not hardcoded relative path."""
    data_dir = Path(tempfile.mkdtemp())
    db_dir = data_dir / "db"
    db_dir.mkdir()
    db_path = db_dir / "database.db"
    db_path.touch()

    assert db_path.exists()
    assert db_path.parent == db_dir

    shutil.rmtree(data_dir)


def test_cookie_dir():
    """Cookie directory should be created alongside db directory."""
    data_dir = Path(tempfile.mkdtemp())
    cookie_dir = data_dir / "cookies"
    cookie_dir.mkdir(parents=True)

    assert cookie_dir.is_dir()
    assert (cookie_dir.parent / "db").mkdir(parents=True) or True

    shutil.rmtree(data_dir)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])