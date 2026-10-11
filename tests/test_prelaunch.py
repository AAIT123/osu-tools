"""No real osu! files, game processes, or credentials used."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from osu_tools import prelaunch
from tests.fixtures import make_collections, make_osudb, make_scores

A = 'a' * 32


class PrelaunchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root/'Songs').mkdir()
        make_osudb(self.root/'osu!.db', [(A, 0, 4)])
        make_collections(self.root/'collection.db', [('all', []), ('std all', [A]),
                                                     ('all loved', []), ('all played', [])])
        make_scores(self.root/'scores.db', [])
        self.env = patch.dict(os.environ, {
            'OSU_SONGS': str(self.root/'Songs'),
            'XDG_CONFIG_HOME': str(self.root/'config'),
            'XDG_CACHE_HOME': str(self.root/'cache'),
            'XDG_DATA_HOME': str(self.root/'data'),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.running = patch('osu_tools.prelaunch.game_is_running', return_value=False)
        self.running.start()
        self.addCleanup(self.running.stop)

    def invoke(self, args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return prelaunch.main_prelaunch(args)

    def test_opt_in_preview_and_apply_modes(self):
        self.assertEqual(prelaunch.load_config()['mode'], 'off')
        self.assertEqual(self.invoke(['run']), 0)
        self.assertFalse(prelaunch.state_path().exists())
        self.assertEqual(self.invoke(['enable', '--preview']), 0)
        self.assertEqual(prelaunch.load_config()['mode'], 'preview')
        self.assertEqual(self.invoke(['enable', '--apply', '--max-additions', '20']), 0)
        item = prelaunch.load_config()
        self.assertEqual((item['mode'], item['max_additions']), ('apply', 20))
        self.assertEqual(prelaunch.config_path().stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.invoke(['disable']), 0)
        self.assertEqual(prelaunch.load_config()['mode'], 'off')

    def test_only_run_if_file_changed_or_interval_expired(self):
        self.invoke(['enable', '--preview'])
        with patch('osu_tools.cli.main_collections', return_value=0) as cli:
            self.assertEqual(self.invoke(['run']), 0)
            self.assertEqual(self.invoke(['run']), 0)
            self.assertEqual(cli.call_count, 1)
            # Personal policy modifications must also trigger a new check.
            config = self.root/'config'/'osu-tools'/'collections.json'
            config.write_text('{}')
            self.assertEqual(self.invoke(['run']), 0)
            self.assertEqual(cli.call_count, 2)
            self.assertEqual(self.invoke(['run', '--force-check']), 0)
            self.assertEqual(cli.call_count, 3)

    def test_apply_never_prunes_forces_or_bypasses_cap(self):
        self.invoke(['enable', '--apply'])
        with patch('osu_tools.cli.main_collections', return_value=0) as cli:
            self.invoke(['run'])
        argv = cli.call_args.args[0]
        self.assertEqual(argv, ['sync', '--apply', '--max-additions', '100',
                                '--max-removals', '0'])
        self.assertNotIn('--allow-large', argv)
        self.assertNotIn('--force', argv)
        self.assertNotIn('--prune-mismatches', argv)
        self.assertNotIn('--from-root', argv)

    def test_failed_run_never_records_success(self):
        self.invoke(['enable', '--preview'])
        with patch('osu_tools.cli.main_collections', return_value=1) as cli:
            self.assertEqual(self.invoke(['run']), 1)
            self.assertEqual(self.invoke(['run']), 1)
            self.assertEqual(cli.call_count, 2)
        self.assertFalse(prelaunch.state_path().exists())

    def test_real_apply_writes_safe_verified_backup(self):
        self.invoke(['enable', '--apply'])
        original = (self.root/'collection.db').read_bytes()
        # The game process is mocked as not running, but the full sync and
        # atomic on-disk backup path run on synthetic database fixtures.
        with patch('osu_tools.safety.game_is_running', return_value=False):
            self.assertEqual(self.invoke(['run']), 0)
        self.assertNotEqual((self.root/'collection.db').read_bytes(), original)
        backups = list(self.root.glob('collection.db.bak.*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        state = json.loads(prelaunch.state_path().read_text())
        self.assertIn(str(self.root/'collection.db'), state['sources'])
        self.assertEqual(self.invoke(['run']), 0)
        self.assertEqual(len(list(self.root.glob('collection.db.bak.*'))), 1)

    def test_auto_apply_bulk_limit_rejects_without_writing(self):
        self.invoke(['enable', '--apply'])
        many = [(f'{i:032x}', 0, 7) for i in range(101)]
        make_osudb(self.root/'osu!.db', many)
        original = (self.root/'collection.db').read_bytes()
        with patch('osu_tools.safety.game_is_running', return_value=False):
            self.assertEqual(self.invoke(['run']), 1)
        self.assertEqual((self.root/'collection.db').read_bytes(), original)
        self.assertFalse(list(self.root.glob('collection.db.bak.*')))
        self.assertFalse(prelaunch.state_path().exists())
        self.assertIn('BULK-CHANGE WARNING',
                      (self.root/'cache'/'osu-tools'/'prelaunch.log').read_text())

    def test_private_log_and_changed_sources_during_preview(self):
        self.invoke(['enable', '--preview'])
        with patch('osu_tools.cli.main_collections', return_value=0) as cli:
            self.invoke(['run'])
            log = self.root/'cache'/'osu-tools'/'prelaunch.log'
            self.assertEqual(log.stat().st_mode & 0o777, 0o600)
            self.assertEqual(cli.call_count, 1)
            # A source change *while* a preview runs must not be accepted
            # as a new, successfully previewed source version.
            (self.root/'osu!.db').write_bytes((self.root/'osu!.db').read_bytes() + b'x')
            def mutate(_):
                with (self.root/'osu!.db').open('ab') as handle:
                    handle.write(b'x')
                return 0
            with patch('osu_tools.cli.main_collections', side_effect=mutate):
                self.assertEqual(self.invoke(['run']), 1)
            self.assertNotEqual(prelaunch._last_state()['sources'], prelaunch._fingerprints())

    def test_running_game_is_skipped_even_when_due(self):
        self.invoke(['enable', '--apply'])
        with patch('osu_tools.prelaunch.game_is_running', return_value=True), \
             patch('osu_tools.cli.main_collections') as cli:
            self.assertEqual(self.invoke(['run']), 0)
            cli.assert_not_called()

    def test_invalid_config_and_symlink_refused(self):
        self.invoke(['enable'])
        prelaunch.config_path().write_text('{"mode":"apply"}')
        with self.assertRaises(ValueError):
            prelaunch.load_config()
        prelaunch.config_path().unlink()
        prelaunch.config_path().symlink_to(self.root/'osu!.db')
        with self.assertRaises(ValueError):
            self.invoke(['enable'])

    def test_interval_zero_always_runs(self):
        self.invoke(['enable', '--interval-hours', '0'])
        with patch('osu_tools.cli.main_collections', return_value=0) as cli:
            self.invoke(['run'])
            self.invoke(['run'])
            self.assertEqual(cli.call_count, 2)


if __name__ == '__main__':
    unittest.main()
