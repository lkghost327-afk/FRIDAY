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
        self.selections = {}

    def list_windows(self, app):
        from .automation_worker import identity
        windows = self.windows(app)
        snapshot = [identity(window) for window in windows]
        self.selections[app.casefold().strip()] = (time.monotonic(), snapshot)
        if not windows:
            return f'No open windows for {app}.'
        return '\n'.join(f'{app} window {index}: {window.title}' for index, window in enumerate(windows, 1)) + '\nUse that window number within 60 seconds.'

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
        if canonical == 'browser':
            identities.update({'chrome', 'msedge', 'firefox'})
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
        selector = re.fullmatch(r'(.+?) window (\d+)', app.strip(), re.I)
        if selector:
            from .automation_worker import validate
            name, number = selector.group(1), int(selector.group(2))
            when, snapshot = self.selections.get(name.casefold().strip(), (0, []))
            if time.monotonic() - when > 60 or not 1 <= number <= len(snapshot):
                raise ValueError(f'List windows in {name} first; window numbers expire after 60 seconds.')
            chosen = snapshot[number - 1]
            validate(chosen)
            for window in self.windows(name):
                if window.hwnd == chosen['hwnd'] and window.pid == chosen['pid']:
                    return window
            raise ValueError('The selected window changed. List windows again.')
        windows = self.windows(app)
        if not windows:
            raise ValueError(f'No open window for {app}. Open it first.')
        if len(windows) != 1:
            raise ValueError(f'{app} has {len(windows)} windows. Say list windows in {app}, then use {app} window 1 (or another listed number).')
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

    def close_selected(self, app):
        from .actions import NEVER_CLOSE_PROCESSES, _process_identity
        target = self.one(app)
        if target.pid == os.getpid() or _process_identity(target.process_name) in NEVER_CLOSE_PROCESSES:
            raise ValueError('That system or assistant window is protected.')
        if self.router.cancelled():
            raise ValueError('App action cancelled.')
        if not self.router._post_window_close(target.hwnd):
            raise ValueError('Windows did not accept the close request.')
        deadline = time.monotonic() + 2.5
        while not self.router.cancelled() and not self.router._stop.is_set():
            if not any(w.hwnd == target.hwnd and w.pid == target.pid for w in self.router._user_windows()):
                return f'Confirmed: {app} closed.'
            if time.monotonic() >= deadline:
                break
            self.router._stop.wait(.1)
        return f'Close requested for {app}; it may be waiting for an unsaved-work prompt. Nothing was force-closed.'

    def controls(self, app, operation, text=''):
        from .actions import NEVER_CLOSE_PROCESSES, _process_identity
        from .automation_worker import automate, identity, isolated
        app = self.resolve_reference(app)
        target = self.one(app)
        process = _process_identity(target.process_name)
        if target.pid == os.getpid() or (process in NEVER_CLOSE_PROCESSES and process != 'explorer'):
            raise ValueError('That system or assistant window is protected.')
        if operation not in {'list', 'search', 'button', 'navigate'} or len(text) > 2000:
            raise ValueError('Choose list, search, button or navigation, with at most 2,000 characters.')
        # Capture the bound request callback; newer conversation jobs cannot revive this job.
        result = isolated(automate, (identity(target), app, operation, text), self.router.cancelled)
        self.remember(app)
        return result
