// Execute original and current next_windows SQL on synthetic PostgreSQL fixtures.
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const {PGlite} = require(process.env.PGLITE_PACKAGE_ROOT || '@electric-sql/pglite');
const python = process.env.PYTHON || 'python3';
function call(mode, value) {
  const result = spawnSync(python, ['scripts/test_yoon_windows_projection.py', mode], {
    cwd: root, input: value, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024,
    env: {...process.env, PYTHONPATH: root, PYTHONDONTWRITEBYTECODE: '1'},
  });
  if (result.status !== 0) throw Error(result.stderr);
  return JSON.parse(result.stdout);
}
const input = call('input');
const convert = sql => {let index = 0; return sql.replace(/%s/g, () => `$${++index}`);};
const oldSql = convert(input.old_sql), newSql = convert(input.new_sql);
const db = new PGlite();
await db.exec(`CREATE SCHEMA ops;
  CREATE TABLE ops.set_run_leases(id uuid PRIMARY KEY,set_run_id uuid,segment_start_index integer,status text);
  CREATE TABLE ops.segment_hits(set_run_id uuid,segment_index integer,raw_data jsonb);`);
const cases = [];
for (const fixture of input.fixtures) {
  await db.query('INSERT INTO ops.set_run_leases VALUES($1,$1,0,\'pending\')', [fixture.id]);
  if (!fixture.no_hit) await db.query('INSERT INTO ops.segment_hits VALUES($1,0,$2::jsonb)',
    [fixture.id, fixture.sql_null ? null : JSON.stringify(fixture.raw)]);
  const params = [fixture.id, 10, 1, 0, 10];
  cases.push({label: fixture.label, old: (await db.query(oldSql, params)).rows,
    new: (await db.query(newSql, params)).rows});
}
// Verify ordering/slot/status/valid filtering/limits with interleaved candidates.
const run = '00000000-0000-4000-8000-000000000001';
for (let index = 39; index >= 0; index--) {
  const id = `10000000-0000-4000-8000-${String(index).padStart(12, '0')}`;
  await db.query('INSERT INTO ops.set_run_leases VALUES($1,$2,$3,$4)',
    [id, run, index, index % 7 === 0 ? 'claimed' : 'pending']);
  if (index % 5 === 0) await db.query('INSERT INTO ops.segment_hits VALUES($1,$2,$3::jsonb)',
    [run, index, JSON.stringify({private_jackson_v2: {valid: true, next_allowed_at: 9999}})]);
}
const ordering = [];
for (const slots of [1, 2, 3, 12]) for (let slot = 0; slot < slots; slot++) {
  for (const size of [1, 3, 10]) for (const limit of [1, 2, 10, 479]) {
    const params = [run, size, slots, slot, limit];
    const old = (await db.query(oldSql, params)).rows, next = (await db.query(newSql, params)).rows;
    assert.deepEqual(old, next);
    const expected = Array.from({length: 40}, (_, index) => index)
      .filter(index => index % 7 !== 0 && index % 5 !== 0 && Math.floor(index / size) % slots === slot)
      .slice(0, limit);
    assert.deepEqual(next.map(row => row.segment_index), expected);
    ordering.push({old, new: next});
  }
}
const large = cases.find(fixture => fixture.label === 'large-valid-shape');
const bytes = value => Buffer.byteLength(JSON.stringify(value));
const sizes = {allOriginalBytes: bytes(cases.map(row => row.old)), allProjectedBytes: bytes(cases.map(row => row.new)),
  largeOriginalBytes: bytes(large.old), largeProjectedBytes: bytes(large.new)};
const numericRows = cases.flatMap(row => row.new).filter(row =>
  typeof row.raw_data?.private_jackson_v2?.next_allowed_at === 'number');
sizes.numericSingleCandidateMinBytes = Math.min(...numericRows.map(row => bytes([row])));
sizes.numericSingleCandidateMaxBytes = Math.max(...numericRows.map(row => bytes([row])));
const widestNumeric = numericRows.reduce((a, b) => bytes(a) > bytes(b) ? a : b);
sizes.tenNumericCandidatesWithThreeDigitIndicesBytes = bytes(Array.from({length: 10},
  (_, index) => ({...widestNumeric, segment_index: 469 + index})));
assert(sizes.largeProjectedBytes < sizes.largeOriginalBytes / 1000);
const before = (await db.query('SELECT set_run_id,segment_index,raw_data FROM ops.segment_hits ORDER BY set_run_id,segment_index')).rows;
await db.query(newSql, [large.old[0].id, 10, 1, 0, 10]);
const after = (await db.query('SELECT set_run_id,segment_index,raw_data FROM ops.segment_hits ORDER BY set_run_id,segment_index')).rows;
assert.deepEqual(before, after); // projected reads never modify durable raw evidence
console.log(JSON.stringify(call('compare', JSON.stringify({cases, ordering, sizes}))));
await db.close();
