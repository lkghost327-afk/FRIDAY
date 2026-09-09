"""Start FRIDAY; importing this file has no side effects."""
if __name__ == "__main__":
    from assistant_core.app import launch
    raise SystemExit(launch("friday", __file__))
