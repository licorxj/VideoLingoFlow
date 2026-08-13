"""Test port detection and auto-increment logic."""
import socket
import threading
import time


def is_port_available(port):
    """Check if a port is available for binding."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def find_available_port(start_port=5409, max_attempts=10):
    """Find an available port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"Could not find available port in range {start_port}-{start_port + max_attempts}")


def test_port_available_returns_true_when_free():
    """Free ports should be detected as available."""
    assert is_port_available(54321)


def test_find_available_port_returns_first_free():
    """find_available_port should return the start port when it's free."""
    port = find_available_port(54321, max_attempts=5)
    assert port == 54321


def test_find_available_port_skips_used():
    """find_available_port should skip ports that are in use."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 54322))
    server.listen(1)

    try:
        port = find_available_port(54322, max_attempts=5)
        assert port > 54322
    finally:
        server.close()


def test_find_available_port_raises_on_all_used():
    """find_available_port should raise RuntimeError when all ports in range are used."""
    import pytest
    sockets = []
    for port in range(54330, 54340):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            s.listen(1)
            sockets.append(s)
        except OSError:
            pass

    try:
        with pytest.raises(RuntimeError, match="Could not find available port"):
            find_available_port(54330, max_attempts=10)
    finally:
        for s in sockets:
            s.close()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])