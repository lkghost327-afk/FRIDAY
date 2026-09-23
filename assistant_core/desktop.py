"""Window-aware actions and bounded UI Automation on explicitly named apps."""
import ctypes
import os
import re
import time
from urllib.parse import quote


class DesktopActions:
    def __init__(self, router):
        self.router = router
        self.last_app = None
        self.last_used = 0.0

    def resolve_reference(self, app):
        if app.lower().strip() in {'it', 'that', 'that app', 'this app', 'the app'}:
            if not self.last_app or time.monotonic() - self.last_used > 300:
                raise ValueError('Name the app first; the previous app context has expired.')
            return self.last_app
        return app

    def remember(self, app):
        self.last_app, self.last_used = app, time.monotonic()

    def windows(self, app):
        from .actions import APP_ALIASES, SHARED_HOST_PROCESSES, _normalize_app_name, _process_identity
        app = self.resolve_reference(app)
        normalized = _normalize_app_name(app)
        canonical = APP_ALIASES.get(normalized, normalized)
        identities = {_process_identity(canonical), _process_identity(normalized)}
        installed, issue = self.router._resolve_installed_app(app)
        if issue:
            raise ValueError(issue)
        if installed:
            identities.update(_process_identity(p) for p in installed.process_names)
            identities.add(_process_identity(installed.name))
        result = []
        for window in self.router._user_windows():
            process = _process_identity(window.process_name)
            if process in SHARED_HOST_PROCESSES and process not in identities:
                continue
            if process in identities or (installed and not installed.process_names
                                         and _normalize_app_name(window.title) == normalized):
                result.append(window)
        return result

    def one(self, app):
        windows = self.windows(app)
        if not windows:
            raise ValueError(f'No open window for {app}. Open it first.')
        if len(windows) != 1:
            raise ValueError(f'{app} has {len(windows)} windows. Make the target unambiguous first.')
        return windows[0]

    def verify(self, app, opened, timeout=2.5):
        deadline = time.monotonic() + timeout
        while True:
            if self.router.cancelled():
                return 'Verification cancelled.'
            windows = self.windows(app)
            if bool(windows) == opened:
                if opened:
                    self.remember(app)
                return f'Confirmed: {app} is {"open" if opened else "closed"}.'
            if self.router._stop.is_set() or time.monotonic() >= deadline:
                return (f'{app} has not shown a window yet; launch is not confirmed.' if opened else
                        f'{app} is still open. Check for an unsaved-work or confirmation dialog.')
            self.router._stop.wait(.1)

    def window_control(self, app, action):
        from .actions import NEVER_CLOSE_PROCESSES, _process_identity
        app = self.resolve_reference(app)
        target = self.one(app)
        if target.pid == os.getpid() or _process_identity(target.process_name) in NEVER_CLOSE_PROCESSES:
            raise ValueError('That system or assistant window is protected.')
        user32 = ctypes.windll.user32
        from ctypes import wintypes
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.IsIconic.argtypes = user32.IsZoomed.argtypes = [wintypes.HWND]
        user32.GetForegroundWindow.restype = wintypes.HWND
        codes = {'minimize': 6, 'maximize': 3, 'restore': 9, 'focus': 9}
        if action not in codes:
            raise ValueError('Choose minimize, maximize, restore or focus.')
        user32.ShowWindow(target.hwnd, codes[action])
        if action == 'focus':
            user32.SetForegroundWindow(target.hwnd)
        self.router._stop.wait(.1)
        confirmed = (bool(user32.IsIconic(target.hwnd)) if action == 'minimize' else
                     bool(user32.IsZoomed(target.hwnd)) if action == 'maximize' else
                     user32.GetForegroundWindow() == target.hwnd if action == 'focus' else
                     not user32.IsIconic(target.hwnd) and not user32.IsZoomed(target.hwnd))
        self.remember(app)
        return f'{action.title()} {app}: ' + ('confirmed.' if confirmed else 'requested; Windows has not confirmed the change.')

    def controls(self, app, operation, text=''):
        """Use exact accessible control names; never coordinate-click or type a shell command."""
        from .actions import NEVER_CLOSE_PROCESSES, _process_identity
        app = self.resolve_reference(app)
        target = self.one(app)
        if target.pid == os.getpid() or _process_identity(target.process_name) in NEVER_CLOSE_PROCESSES:
            raise ValueError('That system or assistant window is protected.')
        if operation not in {'list', 'search', 'button'}:
            raise ValueError('Choose list, search or button.')
        if operation == 'search' and app.casefold() == 'spotify':
            os.startfile('spotify:search:' + quote(text, safe=''))
            self.remember(app)
            return f'Asked Spotify to search for {text}.'
        import pythoncom
        pythoncom.CoInitialize()
        try:
            from pywinauto import Desktop
            window = Desktop(backend='uia').window(handle=target.hwnd).wrapper_object()
            if operation == 'list':
                names = [c.window_text() for c in window.descendants(control_type='Button', depth=6)
                         if c.is_visible() and c.is_enabled() and c.window_text()]
                return 'Available buttons: ' + ', '.join(dict.fromkeys(names[:40])) if names else 'No accessible buttons found.'
            if operation == 'search':
                candidates = [c for c in window.descendants(control_type='Edit', depth=6)
                              if 'search' in c.window_text().casefold() and c.is_visible() and c.is_enabled()]
                if len(candidates) != 1:
                    raise ValueError('I could not identify one accessible Search field in that app.')
                candidates[0].set_edit_text(text)
                if candidates[0].get_value() != text:
                    raise ValueError('The app did not confirm the search text.')
                candidates[0].type_keys('{ENTER}')
                result = f'Entered and submitted the search in {app}.'
            else:
                if re.search(r'\b(send|delete|remove|buy|pay|purchase|confirm|install|transfer|format)\b', text, re.I):
                    raise ValueError('Use the app directly for that consequential button.')
                candidates = [c for c in window.descendants(control_type='Button', depth=6)
                              if c.window_text().casefold() == text.casefold() and c.is_visible() and c.is_enabled()]
                if len(candidates) != 1:
                    raise ValueError('I could not identify one enabled button with that exact name. Try list buttons in the app.')
                candidates[0].invoke()
                result = f'The {text} button in {app} accepted the action.'
            self.remember(app)
            return result
        finally:
            pythoncom.CoUninitialize()
