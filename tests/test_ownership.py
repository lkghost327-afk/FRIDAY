import hashlib
from pathlib import Path
import unittest
from assistant_core.ownership import details, PUBLISHER_KEY_SHA256


class OwnershipTests(unittest.TestCase):
    def test_publisher_key_is_pinned_to_repo_file(self):
        key = Path(__file__).resolve().parents[1] / 'PUBLISHER-KEY.xml'
        self.assertEqual(hashlib.sha256(key.read_bytes()).hexdigest(), PUBLISHER_KEY_SHA256)
        self.assertNotIn(b'<D>', key.read_bytes())

    def test_personas_identify_their_original_repositories(self):
        for persona, name in [('friday','FRIDAY'),('alfred','ALFRED')]:
            identity = details(persona)
            self.assertEqual(identity['publisher'],'lkghost327-afk')
            self.assertEqual(identity['repository'],'https://github.com/lkghost327-afk/'+name)
