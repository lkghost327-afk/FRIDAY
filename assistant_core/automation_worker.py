"""Killable UI Automation with a verified, immutable window identity."""
import multiprocessing
import os
import re
import time
from urllib.parse import quote


def health_check():
    """Exercise the same frozen worker entry point without touching any app."""
    return 'ready'


def _entry(connection, function, arguments):
    try:
        # The parent checks cancellation again after Windows has spawned us.
        if connection.recv() != 'run':
            return
        connection.send(('ok', function(*arguments)))
    except (EOFError, BrokenPipeError):
        pass
    except Exception as error:
        try:
            connection.send(('error', str(error) if isinstance(error, ValueError) else
                             'The app did not respond to accessible controls.'))
        except (EOFError, BrokenPipeError):
            pass
    finally:
        connection.close()


def isolated(function, arguments, cancelled, timeout=6):
    """Terminate and reap the process on timeout/cancel; no queued action survives."""
    if cancelled():
        raise ValueError('App action cancelled.')
    context = multiprocessing.get_context('spawn')
    parent, child = context.Pipe()
    worker = context.Process(target=_entry, args=(child, function, arguments), daemon=True)
    started = False
    deadline = time.monotonic() + timeout
    try:
        worker.start()
        started = True
        child.close()
        if cancelled():
            raise ValueError('App action cancelled.')
        parent.send('run')
        while True:
            if cancelled():
                raise ValueError('App action cancelled; no further controls will be pressed.')
            if time.monotonic() >= deadline:
                raise ValueError('The app did not respond in time. Its automation worker was stopped.')
            if parent.poll(.02):
                try:
                    status, result = parent.recv()
                except EOFError:
                    raise ValueError('The app automation worker exited unexpectedly.') from None
                if cancelled():
                    raise ValueError('App action cancelled.')
                if status != 'ok':
                    raise ValueError(result)
                return result
            if not worker.is_alive():
                raise ValueError('The app automation worker exited unexpectedly.')
    finally:
        if started:
            if worker.is_alive():
                worker.terminate()
            worker.join(1)
            if worker.is_alive():
                worker.kill()
                worker.join(1)
            worker.close()
        parent.close()
        child.close()


def identity(target):
    import psutil
    return {'hwnd': target.hwnd, 'pid': target.pid,
            'created': psutil.Process(target.pid).create_time(),
            'process': target.process_name, 'title': target.title}


def validate(target, foreground=False):
    import psutil
    import win32gui
    import win32process
    from .actions import NEVER_CLOSE_PROCESSES, _process_identity
    handle = target['hwnd']
    process = _process_identity(target['process'])
    if (target['pid'] == os.getpid() or
            (process in NEVER_CLOSE_PROCESSES and process != 'explorer')):
        raise ValueError('That system or assistant window is protected.')
    if (not win32gui.IsWindow(handle) or not win32gui.IsWindowVisible(handle) or
            win32process.GetWindowThreadProcessId(handle)[1] != target['pid'] or
            psutil.Process(target['pid']).create_time() != target['created'] or
            _process_identity(psutil.Process(target['pid']).name()) != process):
        raise ValueError('The selected window changed. List windows and try again.')
    if process == 'explorer' and win32gui.GetClassName(handle) != 'CabinetWClass':
        raise ValueError('Only File Explorer folder windows support this action.')
    if foreground and win32gui.GetForegroundWindow() != handle:
        raise ValueError('The target lost focus. No further keys were sent.')


def automate(target, app, operation, text):
    import pythoncom
    from pywinauto import Desktop
    from .actions import _process_identity
    pythoncom.CoInitialize()
    try:
        validate(target)
        if _process_identity(target['process']) == 'spotify':
            action = text if operation == 'navigate' else text.casefold() if operation == 'button' else ''
            if action in {'play','pause','next_track','previous_track'}:
                import asyncio
                from .media_sessions import control_spotify
                result = asyncio.run(control_spotify(action, lambda:validate(target)))
                if result is not None:
                    return result
        import win32gui
        if operation != 'list' and win32gui.IsIconic(target['hwnd']):
            # Navigation is an explicit request to work in this app. Its controls
            # are often absent from UIA while the window is minimized.
            win32gui.ShowWindow(target['hwnd'], 9)
        window = Desktop(backend='uia').window(handle=target['hwnd']).wrapper_object()
        if operation == 'navigate':
            return navigate(target, window, app, text)
        if operation == 'list':
            names = [c.window_text() for c in window.descendants(control_type='Button', depth=6)
                     if c.is_visible() and c.is_enabled() and c.window_text()]
            return 'Available buttons: ' + ', '.join(dict.fromkeys(names[:40])) if names else 'No accessible buttons found.'
        if operation == 'button':
            if re.search(r'\b(send|delete|remove|buy|pay|purchase|confirm|install|transfer|format)\b|भेज|हटा|खरीद|भुगतान|इंस्टॉल|पुष्टि', text, re.I):
                raise ValueError('Use the app directly for that consequential button.')
            if _process_identity(target['process']) == 'explorer':
                raise ValueError('File Explorer supports search, not arbitrary button presses.')
            if _process_identity(target['process']) == 'spotify' and text.casefold() in {'play','pause','next','previous'}:
                return spotify_control(target, window, text.casefold().replace('next','next_track').replace('previous','previous_track'))
            candidates = [c for c in window.descendants(control_type='Button', depth=6)
                          if c.window_text().casefold() == text.casefold() and c.is_visible() and c.is_enabled()]
            if len(candidates) != 1:
                raise ValueError('I could not identify one enabled button with that exact name. Try list buttons in the app.')
            validate(target)
            candidates[0].invoke()
            return f'The {text} button in {app} accepted the action.'
        if operation != 'search':
            raise ValueError('Choose list, search or button.')
        process = _process_identity(target['process'])
        if process == 'spotify':
            validate(target)
            os.startfile('spotify:search:' + quote(text, safe=''))
            return f'Asked Spotify to search for {text}.'
        if process == 'notepad':
            validate(target)
            window.set_focus()
            validate(target, foreground=True)
            window.type_keys('^f', set_foreground=False)
        # UIA Name labels the field; window_text() often returns the current value.
        # Allow a just-opened Find panel to appear, within the worker's deadline.
        browser = process in {'chrome', 'msedge', 'firefox'}
        labels = ('address', 'search or enter', 'search with') if browser else ('find', 'search', 'खोजें', 'ढूंढें') if process == 'notepad' else ('search', 'खोजें')
        until = time.monotonic() + 1.2
        while True:
            validate(target)
            fields = [c for c in window.descendants(control_type='Edit', depth=12)
                      if c.is_visible() and c.is_enabled()]
            candidates = [c for c in fields if any(word in c.element_info.name.casefold() for word in labels)]
            if candidates or time.monotonic() >= until:
                break
            time.sleep(.08)
        # Address bars receive an encoded HTTPS search URL, never user-provided code.
        value = 'https://www.google.com/search?q=' + quote(text, safe='') if browser else text
        if len(candidates) != 1:
            raise ValueError('I could not identify one accessible Search field in that app. No text was entered.')
        field = candidates[0]
        validate(target)
        field.set_edit_text(value)
        if field.get_value() != value:
            raise ValueError('The app did not confirm the search text.')
        validate(target)
        field.set_focus()
        validate(target, foreground=True)
        field.type_keys('{ENTER}', set_foreground=False)
        return f'Entered and submitted the search in {app}.'
    finally:
        pythoncom.CoUninitialize()


def spotify_control(target, window, action):
    """Use player buttons, excluding duplicate Play buttons attached to albums."""
    labels = {'play': {'play', 'चलाएं', 'चलाएँ'}, 'pause': {'pause', 'रोकें'},
              'next_track': {'next', 'next track', 'अगला'},
              'previous_track': {'previous', 'previous track', 'पिछला'}}
    if action == 'play_first_result':
        # Only operate on an accessible Songs section; never guess a screen coordinate.
        sections = [item for item in window.descendants(depth=10)
                    if item.window_text().strip().casefold() in {'songs', 'गाने'}
                    and item.is_visible() and item.element_info.control_type in {'List', 'Group', 'DataGrid'}]
        if len(sections) != 1:
            raise ValueError('Spotify did not expose one Songs results section. Open the Songs results view and try again, or select the track manually.')
        rows = [item for item in sections[0].descendants(depth=5)
                if item.element_info.control_type in {'DataItem', 'ListItem'} and item.is_visible()]
        if not rows:
            raise ValueError('Spotify has not exposed its song results yet. No track was selected.')
        rows.sort(key=lambda item:(item.rectangle().top, item.rectangle().left))
        first = rows[0]
        buttons = [item for item in first.descendants(control_type='Button', depth=4)
                   if item.is_visible() and item.is_enabled() and item.window_text().strip().casefold() in labels['play']]
        if len(buttons) != 1:
            raise ValueError('The first song does not expose a unique Play button. Select it in Spotify directly.')
        validate(target)
        buttons[0].invoke()
        return 'Asked Spotify to play the first song result. Playback is not yet confirmed.'
    if action not in labels:
        raise ValueError('Choose play, pause, next track or previous track for Spotify.')
    bounds = window.rectangle()
    def player_buttons(names):
        return [item for item in window.descendants(control_type='Button', depth=10)
                if item.is_visible() and item.is_enabled() and item.window_text().strip().casefold() in names
                and item.rectangle().top >= bounds.top + (bounds.bottom-bounds.top)*.72]
    buttons = player_buttons(labels[action])
    if not buttons and action in {'play', 'pause'}:
        opposite = 'pause' if action == 'play' else 'play'
        if len(player_buttons(labels[opposite])) == 1:
            return 'Spotify already shows the requested playback state.'
    if len(buttons) != 1:
        raise ValueError('Spotify did not expose one matching player control. Open its main window and select a track first.')
    validate(target)
    buttons[0].invoke()
    if action in {'play', 'pause'}:
        opposite = 'pause' if action == 'play' else 'play'
        until = time.monotonic()+1.5
        while time.monotonic() < until:
            validate(target)
            if len(player_buttons(labels[opposite])) == 1:
                return f'Confirmed: Spotify now shows its {opposite.title()} control.'
            time.sleep(.1)
    return f'Spotify accepted {action.replace("_", " ")}; the resulting track state is not confirmed.'


def navigate(target, window, app, action):
    from .actions import _process_identity
    process = _process_identity(target['process'])
    if process == 'spotify' and action in {'play','pause','next_track','previous_track','play_first_result'}:
        return spotify_control(target, window, action)
    browser = process in {'chrome','msedge','firefox'}
    keys = {}
    if browser or process == 'explorer':
        keys.update(back='%{LEFT}', forward='%{RIGHT}', next_tab='^{TAB}', previous_tab='^+{TAB}', new_tab='^t')
    if process == 'spotify':
        keys.update(back='%{LEFT}', forward='%{RIGHT}', home='%+h', library='%+0', queue='%+q', liked_songs='%+s')
    if process == 'notepad':
        keys.update(next_tab='^{TAB}', previous_tab='^+{TAB}')
    if browser or process in {'explorer','notepad','spotify'}:
        keys.update(scroll_up='{PGUP}', scroll_down='{PGDN}')
    if action not in keys:
        raise ValueError('That navigation command is not supported in this app. Try list buttons in the app.')
    validate(target)
    window.set_focus()
    validate(target, foreground=True)
    window.type_keys(keys[action], set_foreground=False)
    return f'Requested {action.replace("_", " ")} in {app}. Check the app for the resulting view.'
