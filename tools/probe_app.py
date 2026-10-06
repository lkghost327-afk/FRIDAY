"""Read-only accessible-control probe for troubleshooting a named app.

The output may include that app's visible control labels. Review before sharing.
Nothing is clicked, typed, uploaded or saved automatically.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def probe(target):
    import pythoncom
    from pywinauto import Desktop
    from assistant_core.automation_worker import validate
    pythoncom.CoInitialize()
    try:
        validate(target)
        window = Desktop(backend='uia').window(handle=target['hwnd']).wrapper_object()
        result = []
        for item in window.descendants(depth=10):
            kind = item.element_info.control_type
            if kind not in {'Button', 'Edit', 'List', 'DataGrid', 'Group', 'Document', 'ListItem', 'DataItem'} or not item.is_visible():
                continue
            bounds = item.rectangle()
            result.append({'type':kind, 'name':item.window_text()[:100], 'id':item.element_info.automation_id,
                           'bounds':[bounds.left,bounds.top,bounds.right,bounds.bottom]})
            if len(result) == 150:
                break
        return result
    finally:
        pythoncom.CoUninitialize()


def main():
    from assistant_core.actions import ActionRouter
    from assistant_core.automation_worker import isolated, identity
    parser = argparse.ArgumentParser()
    parser.add_argument('app')
    parser.add_argument('--restore', action='store_true', help='Temporarily restore a minimized target, then minimize it again')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as folder:
        router = ActionRouter(folder, 'friday', lambda *args, **kwargs:None)
        restored = None
        try:
            window = router.desktop.one(args.app)
            if args.restore:
                import win32gui
                import time
                if win32gui.IsIconic(window.hwnd):
                    restored = window.hwnd
                    win32gui.ShowWindow(window.hwnd, 9)
                    time.sleep(.7)
            print(json.dumps(isolated(probe, (identity(window),), lambda:False, timeout=12), ensure_ascii=False, indent=2))
        finally:
            if restored is not None and win32gui.IsWindow(restored):
                win32gui.ShowWindow(restored, 6)
            router.close()


if __name__ == '__main__':
    main()
