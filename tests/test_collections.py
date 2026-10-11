import copy
from pathlib import Path
import tempfile
import unittest
from osu_tools.database import load_beatmaps, load_collections, dump_collections, played_hashes
from osu_tools.collections import sync as actual_sync
from osu_tools.policy import Policy

POLICY = Policy(variant_sources={"taiko hd": "taiko all", "mania 7k": "mania all"})
def sync(*a, **kwargs):
    kwargs.setdefault("policy", POLICY)
    return actual_sync(*a, **kwargs)
from tests.fixtures import make_collections, make_osudb, make_scores

A, B, C, D = 'a'*32, 'b'*32, 'c'*32, 'd'*32

class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.osudb = root/'osu!.db'; self.coll = root/'collection.db'; self.scores=root/'scores.db'
        make_osudb(self.osudb, [(A,0,4),(B,1,7),(C,3,4),(D,0,4)])
        make_scores(self.scores, [(A, [(0,0)]), (B,[(1,0)]), (D, [(1,8388608)])])
        make_collections(self.coll, [
            ('all', [A]), ('std all', []), ('taiko all', []), ('mania all', []),
            ('ctb', []), ('std hdhr',[A]), ('taiko hd',[B,D]),
            ('taiko converts',[D]), ('mania 7k',[C]),
            ('all loved',[]), ('all played',[])])
        _,_,self.maps = load_beatmaps(self.osudb)
        self.db=load_collections(self.coll)

    def test_roundtrip_exact(self):
        self.assertEqual(dump_collections(self.db), self.coll.read_bytes())
        self.assertEqual(len(self.maps), 4)
        self.assertEqual(self.maps[B].native_mode, 1)
        self.assertEqual(self.maps[B].beatmapset_id, 201)

    def test_score_reader_exact_difficulty_and_target_practice(self):
        self.assertEqual(played_hashes(self.scores), {A,B,D})

    def test_sync_convert_in_native_not_target_and_warnings(self):
        result=sync(self.db, self.maps, operations=['sync'], played=played_hashes(self.scores))
        self.assertIn(D, self.db.find('taiko converts').hashes)
        self.assertIn(D, self.db.find('taiko all').hashes)  # explicit convert exception
        self.assertNotIn(D, self.db.find('std all').hashes)  # no implicit root -> native
        self.assertIn(B, self.db.find('taiko all').hashes)
        self.assertIn(C, self.db.find('mania all').hashes)
        self.assertIn(D, self.db.find('all').hashes)
        self.assertIn(B, self.db.find('all loved').hashes)
        self.assertEqual(self.db.find('all played').hashes, [A,B,D])
        self.assertTrue(any('taiko hd' in w for w in result.warnings))

    def test_opt_in_prune_removes_only_wrong_native_aggregates(self):
        self.db.find('taiko all').hashes.append(D)  # native standard
        result=sync(self.db,self.maps,operations=['sync'],played=set(),prune_mismatches=True)
        self.assertNotIn('taiko all', result.removals)  # tagged converts are protected
        self.assertIn(D,self.db.find('taiko all').hashes)
        self.assertIn(D,self.db.find('taiko converts').hashes)
        self.assertNotIn(D,self.db.find('std all').hashes)  # no implicit reverse pass
        self.assertIn(D,self.db.find('all').hashes)

    def test_sync_is_idempotent_and_preserves_order(self):
        play = played_hashes(self.scores)
        original=self.db.find('all').hashes[:]
        first=sync(self.db,self.maps,operations=['sync'],played=play)
        data=dump_collections(self.db)
        second=sync(self.db,self.maps,operations=['sync'],played=play)
        self.assertTrue(first.has_changes())
        self.assertFalse(second.has_changes())
        self.assertEqual(dump_collections(self.db),data)
        self.assertEqual(self.db.find('all').hashes[:len(original)],original)

    def test_dry_run_does_not_modify_file(self):
        before=self.coll.read_bytes()
        sync(self.db,self.maps,operations=['sync'], played=played_hashes(self.scores))
        self.assertEqual(self.coll.read_bytes(),before)

    def test_missing_destinations_not_created_without_flag(self):
        db=copy.deepcopy(self.db)
        db.collections=[c for c in db.collections if c.name!='mania all']
        sync(db,self.maps,operations=['sync'],played=set())
        self.assertIsNone(db.find('mania all'))
        sync(db,self.maps,operations=['sync'],played=set(),create_missing=True)
        self.assertIsNotNone(db.find('mania all'))

    def test_reverse_classification_requires_explicit_request(self):
        sync(self.db, self.maps, operations=['sync'], played=set())
        self.assertNotIn(D, self.db.find('std all').hashes)
        second = sync(self.db, self.maps, operations=['sync'], played=set(), from_root=True)
        self.assertIn(D, self.db.find('std all').hashes)
        self.assertEqual(second.sources['std all']['root: all (explicit reverse sync)'], 2)

    def test_native_std_converts_flow_to_mode_all_and_root(self):
        plan = sync(self.db, self.maps, operations=['sync'], played=set())
        self.assertIn(D, self.db.find('taiko all').hashes)
        self.assertIn(D, self.db.find('all').hashes)
        self.assertEqual(plan.sources['taiko all']['explicit standard converts: taiko converts'], 1)
        self.assertFalse(any('taiko all: 1 non-native' in w for w in plan.warnings))

    def test_nonstandard_difficulties_never_propagate_as_converts(self):
        # B = native taiko, C = native mania, D = native standard.
        self.db.find('taiko converts').hashes.extend([B, C, 'f'*32])
        from osu_tools.database import Collection
        self.db.collections.append(Collection('mania converts', [B, D]))
        self.db.collections.append(Collection('ctb converts', [C, D]))
        plan = sync(self.db, self.maps, operations=['sync'], played=set())
        for dest in ('taiko all', 'mania all', 'ctb'):
            self.assertIn(D, self.db.find(dest).hashes)
        self.assertNotIn(C, self.db.find('taiko all').hashes)
        self.assertNotIn(B, self.db.find('mania all').hashes)
        self.assertNotIn(C, self.db.find('ctb').hashes)
        self.assertIn(B, self.db.find('taiko converts').hashes)  # manual data untouched
        self.assertIn('f'*32, self.db.find('taiko converts').hashes)
        self.assertNotIn('f'*32, self.db.find('all').hashes)
        self.assertTrue(any('non-standard' in w for w in plan.warnings))
        self.assertTrue(any('unknown checksum' in w for w in plan.warnings))

    def test_std_converts_legacy_policy_is_ignored_not_crashing(self):
        from osu_tools.database import Collection
        from osu_tools.policy import Policy
        self.db.collections.append(Collection('std converts', [D]))
        policy = Policy(root_sources=['std converts'])
        plan = actual_sync(self.db, self.maps, operations=['sync'], played=set(), policy=policy)
        self.assertNotIn(D, self.db.find('all').hashes)
        self.assertTrue(any('obsolete' in w for w in plan.warnings))

    def test_target_convert_variant_accepts_only_native_std(self):
        from osu_tools.database import Collection
        from osu_tools.policy import Policy
        self.db.collections.append(Collection('taiko 4k converts', [B, D, 'f'*32]))
        plan = actual_sync(self.db, self.maps, operations=['sync'], played=set(),
                           policy=Policy(variant_sources={'taiko 4k converts':'taiko converts'}))
        self.assertIn(D, self.db.find('taiko converts').hashes)
        self.assertNotIn(B, self.db.find('taiko converts').hashes)
        self.assertNotIn('f'*32, self.db.find('taiko converts').hashes)
        self.assertIn(D, self.db.find('taiko all').hashes)
        self.assertTrue(any('non-standard' in w for w in plan.warnings))

    def test_policy_rejects_new_std_convert_target_but_reads_old_root(self):
        from osu_tools.policy import Policy
        config = Policy().to_dict()
        config['variant_sources'] = {'something':'std converts'}
        with self.assertRaises(ValueError):
            Policy.from_dict(config)
        config['variant_sources'] = {}
        config['root_sources'] += ['std converts']
        self.assertIn('std converts', Policy.from_dict(config).root_sources)

    def test_converts_disabled_in_policy(self):
        cfg = Policy(convert_into_mode_all=False)
        plan = actual_sync(self.db, self.maps, operations=['sync'], played=set(), policy=cfg)
        self.assertNotIn(D, self.db.find('taiko all').hashes)
        self.assertIn(D, self.db.find('all').hashes)

    def test_untagged_non_native_map_still_pruned(self):
        self.db.find('taiko all').hashes.append(A)  # no taiko converts tag for A
        plan = sync(self.db, self.maps, operations=['sync'], played=set(), prune_mismatches=True)
        self.assertIn(A, plan.removals['taiko all'])
        self.assertIn(D, self.db.find('taiko all').hashes)

    def test_wrong_native_catch_group_not_a_source_for_root(self):
        self.db.find('taiko converts').hashes.remove(D)
        self.db.find('ctb').hashes.append(D)  # standard difficulty in catch aggregate
        plan = sync(self.db, self.maps, operations=['all'])
        self.assertNotIn(D, self.db.find('all').hashes)
        self.assertTrue(any('ctb: 1 non-native' in w for w in plan.warnings))

    def test_summarizes_variant_mismatch_not_warning_per_hash(self):
        self.db.find('taiko hd').hashes.extend([D] * 200)
        plan = sync(self.db, self.maps, operations=['variants'])
        self.assertEqual(len([w for w in plan.warnings if w.startswith('taiko hd:')]), 1)

    def test_unconfigured_std_hdhr_never_merges_even_for_large_collection(self):
        self.db.find("std hdhr").hashes = [f"{i:032x}" for i in range(2000)]
        plan = actual_sync(self.db, self.maps, operations=["sync"], played=set(), policy=Policy())
        self.assertNotIn("std all", plan.additions)
        self.assertFalse(any("std hdhr" in key for origins in plan.sources.values() for key in origins))

    def test_unknown_hash_kept_and_not_guessed(self):
        h='e'*32
        self.db.find('all').hashes.append(h)
        sync(self.db,self.maps,operations=['sync'],played=set())
        self.assertIn(h,self.db.find('all').hashes)
        for name in ('std all','taiko all','mania all','ctb'):
            self.assertNotIn(h,self.db.find(name).hashes)

if __name__ == '__main__': unittest.main()
