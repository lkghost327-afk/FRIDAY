"""Explicit Spotify media-session control; never operates on the global/current player."""
import asyncio
import re


def is_spotify(identifier):
    return bool(re.fullmatch(r'(?:spotify(?:\.exe)?|SpotifyAB\.SpotifyMusic_[A-Za-z0-9]+!Spotify)', identifier, re.I))


def select_spotify(sessions):
    matches = [session for session in sessions if is_spotify(session.source_app_user_model_id)]
    if len(matches) > 1:
        raise ValueError('More than one Spotify media session is available. Choose a player in Spotify first.')
    return matches[0] if matches else None


async def control_spotify(action, validate=lambda:None):
    """None means no Spotify session; other responses must not be retried in UIA."""
    if action not in {'play','pause','next_track','previous_track','status'}:
        return None
    try:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status
        manager = await asyncio.wait_for(Manager.request_async(), 2)
        session = select_spotify(manager.get_sessions())
    except (ImportError, OSError, asyncio.TimeoutError):
        return None
    if session is None:
        return None
    info = session.get_playback_info()
    if action == 'status':
        return f'Spotify media session: {info.playback_status.name.lower()}.'
    desired = Status.PLAYING if action == 'play' else Status.PAUSED if action == 'pause' else None
    if desired is not None and info.playback_status == desired:
        return f'Confirmed: Spotify is already {desired.name.lower()}.'
    method, enabled = {'play':('try_play_async','is_play_enabled'),
        'pause':('try_pause_async','is_pause_enabled'), 'next_track':('try_skip_next_async','is_next_enabled'),
        'previous_track':('try_skip_previous_async','is_previous_enabled')}[action]
    if not getattr(info.controls, enabled):
        return f'Spotify currently disables {action.replace("_", " ")}. Select a playable track in Spotify first.'
    validate()
    try:
        accepted = await asyncio.wait_for(getattr(session, method)(), 2)
    except (OSError, asyncio.TimeoutError):
        return 'Spotify did not confirm the media request. Check the app before trying again.'
    if not accepted:
        return 'Spotify declined the media request. Check the active device and selected track in Spotify.'
    if desired is not None:
        for _ in range(10):
            validate()
            if session.get_playback_info().playback_status == desired:
                return f'Confirmed: Spotify is {desired.name.lower()}.'
            await asyncio.sleep(.1)
    return f'Spotify accepted {action.replace("_", " ")}; the resulting track state is not confirmed.'
