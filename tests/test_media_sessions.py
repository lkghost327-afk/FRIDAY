"""Only explicitly selected Spotify sessions may receive a media command."""
import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status
from assistant_core.media_sessions import control_spotify, select_spotify


class MediaSessionTests(unittest.TestCase):
    def session(self, name='Spotify.exe', status=Status.PAUSED):
        result = Mock(source_app_user_model_id=name)
        result.get_playback_info.return_value = NS(playback_status=status,
            controls=NS(is_play_enabled=True, is_pause_enabled=True, is_next_enabled=True, is_previous_enabled=True))
        result.try_play_async = AsyncMock(return_value=True)
        result.try_pause_async = AsyncMock(return_value=True)
        result.try_skip_next_async = AsyncMock(return_value=True)
        return result

    def run_action(self, action, sessions, validate=lambda:None):
        manager = Mock()
        manager.get_sessions.return_value = sessions
        with patch('winrt.windows.media.control.GlobalSystemMediaTransportControlsSessionManager',
                   NS(request_async=AsyncMock(return_value=manager))):
            return asyncio.run(control_spotify(action, validate))

    def test_exact_app_selection_rejects_browser_and_duplicates(self):
        browser = self.session('chrome.exe')
        spotify = self.session('SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify')
        self.assertIs(select_spotify([browser, spotify]), spotify)
        self.assertIsNone(select_spotify([browser, self.session('not-spotify.exe')]))
        with self.assertRaises(ValueError):
            select_spotify([spotify, self.session()])

    def test_pause_is_idempotent_and_does_not_toggle(self):
        spotify = self.session()
        self.assertIn('already paused', self.run_action('pause', [spotify]))
        spotify.try_pause_async.assert_not_called()

    def test_play_confirms_result_without_controlling_other_players(self):
        browser, spotify = self.session('chrome.exe'), self.session()
        before = spotify.get_playback_info.return_value
        after = NS(playback_status=Status.PLAYING, controls=before.controls)
        spotify.get_playback_info.side_effect = [before, after]
        self.assertIn('Confirmed', self.run_action('play', [browser, spotify]))
        spotify.try_play_async.assert_awaited_once()
        browser.try_play_async.assert_not_called()

    def test_disabled_rejected_or_cancelled_actions_do_not_retry(self):
        spotify = self.session()
        spotify.get_playback_info.return_value.controls.is_play_enabled = False
        self.assertIn('disables', self.run_action('play', [spotify]))
        spotify.try_play_async.assert_not_called()
        spotify.try_skip_next_async.return_value = False
        self.assertIn('declined', self.run_action('next_track', [spotify]))
        spotify.try_skip_next_async.assert_awaited_once()
        validate = Mock(side_effect=ValueError('cancelled'))
        with self.assertRaises(ValueError):
            self.run_action('next_track', [spotify], validate)
        self.assertEqual(spotify.try_skip_next_async.await_count, 1)

    def test_missing_session_allows_accessible_ui_fallback(self):
        self.assertIsNone(self.run_action('play', [self.session('chrome.exe')]))


if __name__ == '__main__':
    unittest.main()
