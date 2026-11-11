"""Keep compact window selection narrow; SQL semantics run separately in PGlite."""
from unittest import TestCase

from scripts.test_yoon_windows_projection import ORIGINAL_SQL, current_sql, outcome


class WindowProjectionTests(TestCase):
    def test_projection_leaves_all_filters_order_limit_and_locking_unchanged(self):
        old = ORIGINAL_SQL.split('FROM ops.set_run_leases', 1)[1]
        new = current_sql().split('FROM ops.set_run_leases', 1)[1]
        self.assertEqual(new, old)
        self.assertIn('FOR UPDATE OF l SKIP LOCKED', new)
        self.assertIn('ELSE h.raw_data END AS raw_data', current_sql())

    def test_missing_due_is_not_explicit_null(self):
        def candidate(raw):
            return [{'id': 'synthetic', 'segment_index': 0, 'raw_data': raw}]
        missing, _ = outcome(candidate({'private_jackson_v2': {}}), {}, 0)
        explicit_null, _ = outcome(candidate({'private_jackson_v2': {'next_allowed_at': None}}), {}, 0)
        self.assertEqual(missing, ['returned', [('synthetic', 0)], 0])
        self.assertEqual(explicit_null[:2], ['raised', 'TypeError'])

    def test_real_method_keeps_parameter_and_return_contract(self):
        rows = [{'id': 'synthetic', 'segment_index': 11,
                 'raw_data': {'private_jackson_v2': {'next_allowed_at': 120}}}]
        result, calls = outcome(rows, {}, 100, slot=1, slots=2, size=10, limit=9999)
        self.assertEqual(result, ['returned', [('synthetic', 11)], 20])
        self.assertEqual(calls[0][1], ('00000000-0000-4000-8000-000000000001', 10, 2, 1, 479))

    def test_malformed_shapes_still_raise_but_falsey_values_keep_zero_default(self):
        for shape in (True, 1, 'bad', [1]):
            for raw in (shape, {'private_jackson_v2': shape}):
                result, _ = outcome([{'id': 'x', 'segment_index': 0, 'raw_data': raw}], {}, 0)
                self.assertEqual(result[:2], ['raised', 'AttributeError'])
        for shape in (None, False, 0, '', [], {}):
            for raw in (shape, {'private_jackson_v2': shape}):
                result, _ = outcome([{'id': 'x', 'segment_index': 0, 'raw_data': raw}], {}, 0)
                self.assertEqual(result, ['returned', [('x', 0)], 0])
