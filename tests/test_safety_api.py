from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from osu_tools.safety import write_verified, sha256, SafetyError
from osu_tools.api import Client, ApiError

class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'collection.db'
        self.path.write_bytes(b'old')

    def test_verified_unique_backup_and_changes(self):
        with patch('osu_tools.safety.game_is_running', return_value=False):
            backup=write_verified(self.path,b'new',sha256(self.path))
            self.assertEqual(backup.read_bytes(),b'old')
            self.assertEqual(self.path.read_bytes(),b'new')
            second=write_verified(self.path,b'newer',sha256(self.path))
            self.assertNotEqual(backup,second)
            self.assertEqual(second.read_bytes(),b'new')

    def test_stale_snapshot_is_rejected(self):
        before=sha256(self.path)
        self.path.write_bytes(b'changed')
        with patch('osu_tools.safety.game_is_running', return_value=False):
            with self.assertRaises(SafetyError): write_verified(self.path,b'test',before)
        self.assertEqual(self.path.read_bytes(),b'changed')

    def test_running_game_is_rejected(self):
        with patch('osu_tools.safety.game_is_running', return_value=True):
            with self.assertRaises(SafetyError): write_verified(self.path,b'new',sha256(self.path))
        self.assertEqual(self.path.read_bytes(),b'old')

class ApiTests(unittest.TestCase):
    def test_missing_token_handled_without_network(self):
        client=Client(token='test-token')
        self.assertEqual(client.token(),'test-token')
    def test_user_lookup_params(self):
        client=Client(token='fake')
        with patch.object(client,'get',return_value={'id':1}) as get:
            client.user('Some Name', 'osu')
            get.assert_called_with('users/Some%20Name/osu', {'key':'username'})
    def test_checksum_lookup_path(self):
        client=Client(token='fake')
        with patch.object(client,'get',return_value=None) as get:
            self.assertIsNone(client.beatmap_for_checksum('a'*32))
            get.assert_called_with('beatmaps/lookup',{'checksum':'a'*32})

if __name__ == '__main__': unittest.main()
