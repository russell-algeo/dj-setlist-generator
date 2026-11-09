// Builds a credential-free migration folder. Does not connect to any database.
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
export function preparePrivateMigrationStage(root, phase = 'expand') {
  if (!['expand', 'seal', 'recognition'].includes(phase)) throw new Error('Private archive migration phase must be expand, seal or recognition');
  const original = resolve(root, 'drizzle/migrations');
  const journal = JSON.parse(readFileSync(resolve(original, 'meta/_journal.json'), 'utf8'));
  const target = phase === 'expand' ? '0018_private_collection_access'
    : phase === 'seal' ? '0019_private_insert_defaults' : '0020_private_recognition_retention';
  const cutoff = journal.entries.findIndex((entry) => entry.tag === target);
  if (cutoff < 0) throw new Error('Missing private archive migration checkpoint');
  const entries = journal.entries.slice(0, cutoff + 1);
  const folder = resolve(root, '.private-migration-stages', phase);
  mkdirSync(resolve(folder, 'meta'), { recursive: true });
  for (const entry of entries) copyFileSync(resolve(original, `${entry.tag}.sql`), resolve(folder, `${entry.tag}.sql`));
  writeFileSync(resolve(folder, 'meta/_journal.json'), JSON.stringify({ ...journal, entries }, null, 2));
  return folder;
}
