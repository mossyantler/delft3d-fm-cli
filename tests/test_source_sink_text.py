"""Author unsafe-text regressions using literal bytes as expectations.

Every refused preview is followed by a real apply attempt on the disposable
folder. Decoded unsafe text must not reach a staging or publication primitive.
"""
import hashlib
import unittest
from unittest.mock import patch

from dfm_cli import source_sink as subject, source_sink_author as author, source_sink_write as writer
from dfm_cli.common import DfmError
from source_sink_test_fixtures import SourceSinkFixture, UNIT, write_json


def full_snapshot(folder):
    result = {}
    for path in folder.rglob('*'):
        if path.is_file():
            info = path.stat()
            result[path.relative_to(folder).as_posix()] = (hashlib.sha256(path.read_bytes()).hexdigest(),
                info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink)
    return result


class TextValidationTests(SourceSinkFixture, unittest.TestCase):
    def assert_text_refused_both(self, spec, *, action='set'):
        write_json(self.request, spec)  # json.dumps escapes NUL/surrogates independently.
        before = full_snapshot(self.root)
        def invoke(apply, hash=None):
            if action == 'forcing':
                return author.forcing_create(self.request, self.root / 'new.bc', apply=apply, expect_sha256=hash)
            return author.change(self.mdu, self.request, id='Outfall+A' if action == 'set' else None,
                                 add=action == 'add', apply=apply, expect_sha256=hash)
        with patch.object(writer, 'replace', side_effect=AssertionError('unsafe text reached EXT publisher')), \
             patch.object(author.tempfile, 'mkstemp', side_effect=AssertionError('unsafe text reached fresh staging')):
            with self.assertRaises(DfmError) as preview_error:
                invoke(False)
            with self.assertRaises(DfmError) as apply_error:
                invoke(True, '0' * 64)
        self.assertEqual(preview_error.exception.code, 'source_sink_invalid_text')
        self.assertEqual(apply_error.exception.code, preview_error.exception.code)
        self.assertEqual(apply_error.exception.details['reason'], preview_error.exception.details['reason'])
        self.assertEqual(full_snapshot(self.root), before)

    def test_every_C0_C1_DEL_and_unicode_boundary_refuses_preview_apply(self):
        values = [chr(i) for i in range(32)] + [chr(i) for i in range(127, 160)]
        values += ['\u2028', '\u2029', '\ud800', '\udfff', '\u200b', '\u202e', '\u2066']
        for char in values:
            with self.subTest(code_point=f'U+{ord(char):04X}'):
                self.assert_text_refused_both({'version': 1, 'name': 'bad' + char + 'name'})

    def test_edge_whitespace_is_rejected_without_implicit_normalization(self):
        for value in (' padded', 'padded ', '\u00a0padded', 'padded\u00a0', '\u3000padded', 'padded\u3000'):
            with self.subTest(value=repr(value)):
                self.assert_text_refused_both({'version': 1, 'name': value})

    def test_contextual_JSON_escaped_identifiers_refs_units_times_and_rows(self):
        for char in ('\x00', '\x0c', '\u2028', '\ud800'):
            add = {'version': 1, 'id': 'new' + char + 'id',
                   'location': {'coordinates': [['25', '15']]}, 'discharge': {'bc': 'sources.bc'}}
            self.assert_text_refused_both(add, action='add')
            for spec in ({'version': 1, 'discharge': {'bc': 'sources' + char + '.bc'}},
                         {'version': 1, 'location': {'coordinates': [['2' + char + '5', '15']]}},
                         {'version': 1, 'constituents': {'salinity' + char + 'Delta': {'bc': 'sources.bc'}}}):
                self.assert_text_refused_both(spec)
            for context in ('id', 'time_unit', 'quantity', 'unit', 'time', 'value'):
                spec = {'version': 1, 'id': 'NewID', 'time_unit': UNIT,
                        'columns': [{'quantity': 'sourcesink_discharge', 'unit': 'm3/s'},
                                    {'quantity': 'sourcesink_salinityDelta', 'unit': 'ppt'}],
                        'rows': [['0', '0.1', '5'], ['120', '0.1', '15']]}
                if context in ('id', 'time_unit'):
                    spec[context] += char
                elif context in ('quantity', 'unit'):
                    spec['columns'][0][context] += char
                else:
                    spec['rows'][0][0 if context == 'time' else 2] += char
                self.assert_text_refused_both(spec, action='forcing')

    def test_printable_international_labels_preserved_as_exact_UTF8(self):
        for label in ('Normal label 7', '하구 방류구 東京', 'Düsseldorf – Écoulement', 'مصدر مياه تجريبي'):
            with self.subTest(label=label):
                write_json(self.request, {'version': 1, 'name': label})
                raw = (self.root / 'sources.ext').read_bytes()
                preview = author.change(self.mdu, self.request, id='Outfall+A')
                author.change(self.mdu, self.request, id='Outfall+A', apply=True, expect_sha256=preview['sha256'])
                actual = (self.root / 'sources.ext').read_bytes()
                expected = raw.split(b'name = ', 1)
                previous = expected[1].split(b' # keep annotation', 1)[0]
                self.assertEqual(actual, raw.replace(b'name = ' + previous + b' # keep annotation',
                    b'name = ' + label.encode('utf-8') + b' # keep annotation', 1))

    def test_existing_NUL_is_reported_and_only_explicit_clean_repair_admitted(self):
        self.replace('sources.ext', b'name = original name', b'name = bad\x00name')
        inspection = subject.inspect(self.mdu)
        self.assertEqual(inspection['invalid_text_fields'][0]['code_point'], 'U+0000')
        write_json(self.request, {'version': 1, 'area': '0'})
        with self.assertRaises(DfmError) as error:
            author.change(self.mdu, self.request, id='Outfall+A')
        self.assertEqual(error.exception.code, 'source_sink_unsupported_edit')
        write_json(self.request, {'version': 1, 'name': 'Explicit clean repair'})
        preview = author.change(self.mdu, self.request, id='Outfall+A')
        author.change(self.mdu, self.request, id='Outfall+A', apply=True, expect_sha256=preview['sha256'])
        self.assertNotIn(b'\x00', (self.root / 'sources.ext').read_bytes())


if __name__ == '__main__':
    unittest.main(verbosity=2)
