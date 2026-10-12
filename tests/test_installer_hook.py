import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class InstallerHookTests(unittest.TestCase):
    def test_installer_preserves_launcher_and_hooks_only_plain_osu(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = root/'repo'
            repo.mkdir()
            source = Path(__file__).resolve().parent.parent
            (repo/'install.sh').write_bytes((source/'install.sh').read_bytes())
            (repo/'osu').write_text('#!/usr/bin/env bash\n'
                                    'if [ "$#" -eq 0 ]; then echo GAME; else echo ARG:$1; fi\n')
            (repo/'osu-prelaunch').write_text('#!/usr/bin/env bash\n'
                                               'printf "%s\\n" "$*" >> "$OSU_TEST_HOOK_LOG"\n')
            (repo/'osu-scores').write_text('#!/usr/bin/env bash\n'
                                            'printf "SCORE:%s\\n" "$*"\n')
            (repo/'osu-search').write_text('#!/usr/bin/env bash\n'
                                            'printf "SEARCH:%s\\n" "$*"\n')
            (repo/'osu_tools').mkdir()
            (repo/'osu_tools'/'__init__.py').write_text('')
            config = root/'config'/'osu-tools'
            config.mkdir(parents=True)
            (config/'prelaunch.json').write_text('{}')
            bindir, datadir = root/'bin', root/'data'
            env = dict(os.environ, OSU_BIN_DIR=str(bindir), OSU_TOOLS_DIR=str(datadir),
                       XDG_CONFIG_HOME=str(root/'config'), OSU_TEST_HOOK_LOG=str(root/'calls'))
            subprocess.run(['bash', 'install.sh'], cwd=repo, env=env,
                           capture_output=True, text=True, check=True)
            subprocess.run(['bash', '-n', str(bindir/'osu')], check=True)
            def launch(*args, extra=None):
                return subprocess.run([str(bindir/'osu'), *args], env=env | (extra or {}),
                                      capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(launch('doctor'), 'ARG:doctor')
            self.assertEqual(launch('scores', 'recent', '--limit', '5'),
                             'SCORE:recent --limit 5')
            self.assertEqual(launch('search', 'Kobaryo', '--mode', 'taiko'),
                             'SEARCH:Kobaryo --mode taiko')
            self.assertFalse((root/'calls').exists())
            self.assertEqual(launch(), 'GAME')
            self.assertEqual((root/'calls').read_text().strip(), 'run --quiet')
            self.assertEqual(launch(extra={'OSU_TOOLS_SKIP_PRELAUNCH': '1'}), 'GAME')
            self.assertEqual(len((root/'calls').read_text().splitlines()), 1)


if __name__ == '__main__':
    unittest.main()
