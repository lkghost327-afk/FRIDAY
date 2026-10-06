"""Hindi/Hinglish parsing and scoped navigation. No real app is controlled."""
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from assistant_core.actions import ActionRouter
from assistant_core.automation_worker import navigate, spotify_control
from assistant_core.languages import command, is_stop
from assistant_core.settings import Settings
from assistant_core.voice import VoiceService, strip_wake_word


class HindiNavigationTests(unittest.TestCase):
    def test_hindi_and_hinglish_commands_are_explicit_and_negations_are_ignored(self):
        cases = {'Spotify kholo':'open spotify', 'स्पॉटिफाई खोलो':'open Spotify',
            'नोटपैड को बंद करो':'close Notepad', 'कंप्यूटर को बंद करो':'shut down my computer',
            'आवाज़ कम करो':'volume down', 'वॉल्यूम ४० प्रतिशत करो':'volume 40 percent',
            'क्रोम में क्रिकेट सर्च करो':'search Chrome for क्रिकेट',
            'Spotify mein agla gana':'next track in spotify', 'इसे छोटा करो':'minimize it'}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(command(text), expected)
        for text in ('Spotify mat kholo', 'Spotify nahi kholo', 'Spotify कैसे खोलो',
                     'कंप्यूटर बंद मत करो', 'अगर मेरा कंप्यूटर बंद करो', 'क्या Spotify खोलो?'):
            self.assertIsNone(command(text))
        self.assertTrue(is_stop('रुक जाओ।'))

    def test_recognized_names_in_devanagari_and_hindi_voice_choice(self):
        self.assertEqual(strip_wake_word('फ्राइडे, Spotify खोलो', 'friday'), (True, 'Spotify खोलो'))
        self.assertEqual(strip_wake_word('हे अल्फ्रेड समय बताओ', 'alfred'), (True, 'समय बताओ'))
        for persona, name in (('friday', 'hi-IN-SwaraNeural'), ('alfred', 'hi-IN-MadhurNeural')):
            voice = VoiceService(Settings(persona=persona), Mock())
            try:
                self.assertEqual(voice._voice_for('आप कैसे हैं?'), name)
            finally:
                voice.close()

    def test_language_modes_do_not_claim_local_hindi_support(self):
        self.assertEqual(Settings().updated({'recognition_language':'hi-IN'}).recognition_language, 'hi-IN')
        self.assertEqual(Settings().updated({'recognition_language':'auto', 'stt_provider':'deepgram'}).recognition_language, 'auto')
        for provider in ('local','google'):
            with self.assertRaises(ValueError):
                Settings().updated({'recognition_language':'auto','stt_provider':provider})
        with self.assertRaises(ValueError):
            Settings().updated({'recognition_language':'hi-IN','stt_provider':'local'})

    def test_navigation_and_hindi_commands_route_through_validated_tools(self):
        with tempfile.TemporaryDirectory() as folder:
            router = ActionRouter(folder, 'friday', Mock())
            try:
                with patch.object(router, 'execute', return_value='test') as execute:
                    for text, arguments in [('go back in Chrome', {'app':'Chrome','action':'back'}),
                            ('next tab in Edge', {'app':'Edge','action':'next_tab'}),
                            ('Spotify mein agla gana', {'app':'spotify','action':'next_track'}),
                            ('play first result in Spotify', {'app':'Spotify','action':'play_first_result'})]:
                        router.handle(text)
                        execute.assert_called_with('navigate_app', arguments)
                    router.handle('नोटपैड खोलो')
                    execute.assert_called_with('open_app', {'app':'notepad'})
            finally:
                router.close()

    def test_navigation_does_not_send_keys_if_foreground_check_fails(self):
        window = Mock()
        with patch('assistant_core.automation_worker.validate', side_effect=[None, ValueError('lost focus')]):
            with self.assertRaises(ValueError):
                navigate({'process':'chrome.exe'}, window, 'Chrome', 'back')
        window.type_keys.assert_not_called()
        with patch('assistant_core.automation_worker.validate'), self.assertRaises(ValueError):
            navigate({'process':'unknown.exe'}, window, 'Unknown', 'new_tab')
        window.type_keys.assert_not_called()

    def test_spotify_player_ignores_album_play_buttons_and_verifies_state(self):
        window = Mock()
        window.rectangle.return_value = NS(top=0, bottom=1000)
        album, player, pause = Mock(), Mock(), Mock()
        for button, title, top in ((album,'Play',200),(player,'Play',900),(pause,'Pause',900)):
            button.window_text.return_value = title
            button.rectangle.return_value = NS(top=top)
        window.descendants.side_effect = [[album,player], [album,pause]]
        with patch('assistant_core.automation_worker.validate'):
            self.assertIn('Confirmed', spotify_control({}, window, 'play'))
        player.invoke.assert_called_once()
        album.invoke.assert_not_called()

    def test_spotify_ambiguous_player_and_missing_results_do_nothing(self):
        window = Mock()
        window.rectangle.return_value = NS(top=0, bottom=1000)
        buttons = [Mock(),Mock()]
        for button in buttons:
            button.window_text.return_value = 'Play'
            button.rectangle.return_value = NS(top=900)
        window.descendants.return_value = buttons
        with self.assertRaises(ValueError):
            spotify_control({}, window, 'play')
        for button in buttons:
            button.invoke.assert_not_called()
        window.descendants.return_value = []
        with self.assertRaises(ValueError):
            spotify_control({}, window, 'play_first_result')


if __name__ == '__main__':
    unittest.main()
