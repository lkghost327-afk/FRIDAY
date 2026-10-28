"""Offline detector timing tests; no microphone, model download or network."""
import json
import unittest
from unittest.mock import Mock, patch

from assistant_core.wake import LocalWake


class WakeTimingTests(unittest.TestCase):
    def detector(self, persona='friday', sensitivity=50):
        grammar, verifier = Mock(), Mock()
        for decoder in (grammar, verifier):
            decoder.AcceptWaveform.return_value = False
            decoder.PartialResult.return_value = '{"partial":""}'
        with patch('vosk.Model'), patch('vosk.KaldiRecognizer', side_effect=[grammar, verifier] * 2):
            detector = LocalWake(persona, sensitivity)
        return detector, grammar, verifier

    def test_delayed_verifier_retains_original_audio_after_grammar_final(self):
        wake, grammar, verifier = self.detector()
        grammar.AcceptWaveform.return_value = True
        grammar.Result.return_value = '{"text":"friday"}'
        first = b'\x01\x00' * 320
        self.assertIsNone(wake.feed(first))
        grammar.AcceptWaveform.return_value = False
        for _ in range(20):
            self.assertIsNone(wake.feed(bytes(640)))
        verifier.AcceptWaveform.return_value = True
        verifier.Result.return_value = '{"text":"friday open spotify"}'
        frames = wake.feed(bytes(640))
        self.assertEqual(frames[0], first)
        self.assertEqual(len(frames), 22)

    def test_expired_candidate_does_not_combine_with_later_words(self):
        wake, grammar, verifier = self.detector()
        grammar.PartialResult.return_value = '{"partial":"friday"}'
        self.assertIsNone(wake.feed(bytes(640)))
        grammar.PartialResult.return_value = '{"partial":""}'
        for _ in range(65):
            self.assertIsNone(wake.feed(bytes(640)))
        verifier.AcceptWaveform.return_value = True
        verifier.Result.return_value = '{"text":"friday"}'
        self.assertIsNone(wake.feed(bytes(640)))

    def test_verifier_finishing_first_can_wait_for_grammar(self):
        wake, grammar, verifier = self.detector()
        verifier.AcceptWaveform.return_value = True
        verifier.Result.return_value = '{"text":"hello friday"}'
        self.assertIsNone(wake.feed(bytes(640)))
        verifier.AcceptWaveform.return_value = False
        for _ in range(20):
            self.assertIsNone(wake.feed(bytes(640)))
        grammar.AcceptWaveform.return_value = True
        grammar.Result.return_value = '{"text":"hello friday"}'
        self.assertEqual(len(wake.feed(bytes(640))), 22)

    def test_expired_verifier_final_cannot_wake_a_later_grammar(self):
        wake, grammar, verifier = self.detector()
        verifier.AcceptWaveform.return_value = True
        verifier.Result.return_value = '{"text":"friday"}'
        self.assertIsNone(wake.feed(bytes(640)))
        verifier.AcceptWaveform.return_value = False
        for _ in range(65):
            self.assertIsNone(wake.feed(bytes(640)))
        grammar.PartialResult.return_value = '{"partial":"friday"}'
        self.assertIsNone(wake.feed(bytes(640)))

    def test_split_names_and_sensitivity(self):
        for persona, name in [('friday', 'fry day'), ('alfred', 'al fred')]:
            for sensitivity, count in [(80, 1), (50, 2), (20, 3)]:
                with self.subTest(persona=persona, sensitivity=sensitivity):
                    wake, grammar, verifier = self.detector(persona, sensitivity)
                    for decoder in (grammar, verifier):
                        decoder.PartialResult.return_value = json.dumps({'partial':'hey ' + name})
                    for _ in range(count - 1):
                        self.assertIsNone(wake.feed(bytes(640)))
                    self.assertIsNotNone(wake.feed(bytes(640)))

    def test_unrelated_speech_never_activates_for_forced_grammar_match(self):
        for words in ['we will meet on friday', 'Fridayish weather', 'open Spotify', '']:
            wake, grammar, verifier = self.detector()
            grammar.PartialResult.return_value = '{"partial":"friday"}'
            verifier.PartialResult.return_value = json.dumps({'partial':words})
            for _ in range(5):
                self.assertIsNone(wake.feed(bytes(640)))

    def test_reset_discards_pending_name_and_audio(self):
        wake, grammar, verifier = self.detector()
        grammar.PartialResult.return_value = '{"partial":"friday"}'
        wake.feed(bytes(640))
        wake.reset()
        grammar.PartialResult.return_value = '{"partial":""}'
        verifier.PartialResult.return_value = '{"partial":"friday"}'
        for _ in range(5):
            self.assertIsNone(wake.feed(bytes(640)))

