"""Self-tests of independent expected-byte evidence, never candidate acceptance."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from raw_oracle import snapshot,require_exact,require_roles

HERE=Path(__file__).resolve().parent
PRE=HERE/'predeclared-01'

class IndependentOracle(unittest.TestCase):
    def test_carried_manual_corpus_43_exact(self):
        f=json.loads((PRE/'carried/fixture-manifest.json').read_bytes())
        self.assertEqual(len(f['cases']),43)
        for case in f['cases']:
            for name,entry in case['files'].items():
                p=PRE/'carried/fixtures'/case['id']/name
                raw=p.read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(),entry['sha256'])
                self.assertEqual(len(raw),entry['bytes'])

    def test_obligations_and_all_scopes_retained(self):
        self.assertEqual(len(json.loads((PRE/'carried/obligations.json').read_bytes())['obligations']),23)
        ids=[r['id'] for r in json.loads((PRE/'accepted-contract/coverage.json').read_bytes())['rows']]
        self.assertEqual(ids,['W2D','P2D','WTBC','G2D','PTRIGGER','PIL12','PIL3D','PPLIZ','SHP','D1','MODEL3D','LEG','OTHER','GROUP','MULTI','GUI'])

    def test_actual_complete_examples_not_mock_mesh(self):
        for label,count in (('real-pump',6),('real-weir',11)):
            model=PRE/'models'/label
            self.assertEqual(len(list(model.iterdir())),count)
            self.assertGreater((model/'mesh_net.nc').stat().st_size,5000)
            self.assertIn(b'program = D-Flow FM',(model/'model.mdu').read_bytes())
        self.assertIn(b'forcingFile', (PRE/'models/real-weir/boundaries.ext').read_bytes())
        self.assertTrue((PRE/'models/real-weir/boundaries.bc').read_bytes().strip())

    def test_geometry_never_proves_source_hydraulics(self):
        a=PRE/'carried/fixtures/scalar_weir_label_not_id'
        b=PRE/'carried/fixtures/same_geometry_different_crest'
        self.assertEqual((a/'site.pli').read_bytes(),(b/'site.pli').read_bytes())
        self.assertNotEqual((a/'structures.ini').read_bytes(),(b/'structures.ini').read_bytes())
        geometry=(PRE/'literal-expected/geometry-replace.pli').read_bytes()
        self.assertIn(b'Unrelated_0001',geometry)
        self.assertNotIn(b'W_Main',geometry)

    def test_literal_replace_preserves_destination_non_target(self):
        target=(PRE/'models/literal-target/structures.ini').read_bytes()
        expected=(PRE/'literal-expected/hydraulic-replace-structures.ini').read_bytes()
        old=target[target.index(b'[Structure]'):target.index(b'\r\n# file-owned gap',target.index(b'[Structure]'))]
        source=(PRE/'literal-expected/source-weir.core').read_bytes()
        mapped=source.replace(b'locationFile = source-weir.pli',b'locationFile = mapped-source.pli').replace(b'crestLevel = source.tim',b'crestLevel = mapped-crest.tim')
        self.assertEqual(target.replace(old,mapped,1),expected)
        self.assertIn(b'capacity = 0.125000\r\n',expected)
        self.assertIn(b'# path-token-only rewrite\r\n',expected)

    def test_literal_native_projection_is_not_full_file_copy(self):
        general=(PRE/'literal-expected/source-general.core').read_bytes()
        core=(PRE/'literal-expected/source-weir.core').read_bytes()
        projection=(PRE/'literal-expected/export-selected-structures.ini').read_bytes()
        self.assertEqual(projection,general+core)
        self.assertNotIn(b'file-owned',projection)
        self.assertIn(b'interior comment belongs to core',projection)

    def test_TIM_native_minutes_not_model_seconds(self):
        raw=(PRE/'literal-expected/native-minute-crest.tim').read_text()
        data=[line.split() for line in raw.splitlines() if line and not line.startswith('#')]
        self.assertEqual([60*Fraction(t) for t,h in data],[0,60,120])
        self.assertEqual([h for t,h in data],['0.2','0.8','0.3'])

    def test_wrong_role_with_identical_asset_fails(self):
        a=[{'from':'structures.ini','setting':'locationFile','path':'shared.pli','id':'W_Main'}]
        b=[{'from':'structures.ini','setting':'crestLevel','path':'shared.pli','id':'W_Main'}]
        with self.assertRaises(AssertionError):require_roles(a,b)

    def test_adulterated_non_target_detected(self):
        with tempfile.TemporaryDirectory(prefix='G15-V-oracle-') as tmp:
            model=Path(tmp)/'model';shutil.copytree(PRE/'models/real-weir',model)
            original=snapshot(model)
            p=model/'boundaries.bc';p.write_bytes(p.read_bytes()+b'\n# adulterated unselected BC\n')
            with self.assertRaises(AssertionError):require_exact(original,snapshot(model))

    def test_adulterated_target_expected_wrong_bytes_detected(self):
        with tempfile.TemporaryDirectory(prefix='G15-V-oracle-') as tmp:
            model=Path(tmp)/'model';shutil.copytree(PRE/'models/literal-target',model)
            before=snapshot(model)
            expected=(PRE/'literal-expected/hydraulic-replace-structures.ini').read_bytes()
            (model/'structures.ini').write_bytes(expected.replace(b'crestWidth = 4.0000000e1',b'crestWidth = 42'))
            with self.assertRaises(AssertionError):require_exact(before,snapshot(model),{'structures.ini':expected})

if __name__=='__main__':unittest.main(verbosity=2)
