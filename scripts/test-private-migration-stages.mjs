import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { preparePrivateMigrationStage } from './private-migration-stage.mjs';
const require = createRequire(import.meta.url);
const { PGlite } = require('@electric-sql/pglite');
const { pgcrypto } = require('@electric-sql/pglite/contrib/pgcrypto');
const { drizzle } = require('drizzle-orm/pglite');
const { migrate } = require('drizzle-orm/pglite/migrator');
const root = fileURLToPath(new URL('../', import.meta.url));
const db = new PGlite({ extensions: { pgcrypto } });
await db.exec('CREATE ROLE set_list_worker');
const orm = drizzle(db);
const expand = preparePrivateMigrationStage(root);
const seal = preparePrivateMigrationStage(root, 'seal');
assert.throws(() => preparePrivateMigrationStage(root, 'all'));
const expandJournal = JSON.parse(readFileSync(`${expand}/meta/_journal.json`, 'utf8'));
assert.equal(expandJournal.entries.at(-1).tag, '0018_private_collection_access');
assert.equal(expandJournal.entries.some(e => e.tag === '0019_private_insert_defaults'), false);
const options = (folder) => ({ migrationsFolder: folder, migrationsSchema: 'public', migrationsTable: '__drizzle_migrations' });
// The live development database is already at 0017. Build that baseline with
// its unchanged historical SQL, then use the real Drizzle runner for both new phases.
await db.exec('CREATE TABLE public.__drizzle_migrations(id serial PRIMARY KEY, hash text NOT NULL, created_at bigint)');
for (const entry of expandJournal.entries.slice(0, -1)) {
  const sql = readFileSync(`${expand}/${entry.tag}.sql`, 'utf8');
  await db.exec(sql);
  await db.query('INSERT INTO public.__drizzle_migrations(hash,created_at) VALUES ($1,$2)', [createHash('sha256').update(sql).digest('hex'), entry.when]);
}
await migrate(orm, options(expand));
await db.exec("INSERT INTO app.sets(slug,title,normalized_title) VALUES ('legacy-public','Legacy public','legacy public')");
assert.equal((await db.query('SELECT visibility FROM app.sets')).rows[0].visibility, 'public');
const migrationRows = async () => (await db.query('SELECT hash,created_at FROM public.__drizzle_migrations ORDER BY created_at')).rows;
const first = await migrationRows();
assert.equal(first.length, expandJournal.entries.length);
assert.equal(first.at(-1).hash, createHash('sha256').update(readFileSync(`${expand}/0018_private_collection_access.sql`)).digest('hex'));
await migrate(orm, options(expand));
assert.deepEqual(await migrationRows(), first);
await migrate(orm, options(seal));
const second = await migrationRows();
assert.equal(second.length, first.length + 1);
assert.equal(second.at(-1).hash, createHash('sha256').update(readFileSync(`${seal}/0019_private_insert_defaults.sql`)).digest('hex'));
await assert.rejects(db.exec("INSERT INTO app.sets(slug,title,normalized_title) VALUES ('unscoped','Unscoped','unscoped')"));
await migrate(orm, options(seal));
assert.deepEqual(await migrationRows(), second);
console.log('PASS: real Drizzle incremental migration bookkeeping from0017, expand-only default, legacy public insert compatibility, separate seal, exact hashes and idempotence on synthetic PostgreSQL.');
await db.close();
