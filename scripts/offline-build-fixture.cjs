/* Build-only synthetic sitemap fixture. Never reads credentials or calls a DB.
 * Accept exactly the two public sitemap SELECTs, reject all other network fetches.
 */
const empty = { fields: [], rows: [], rowCount: 0, command: 'SELECT', rowAsArray: true };
globalThis.fetch = async (input, options = {}) => {
  const url = new URL(typeof input === 'string' ? input : input.url || String(input));
  if (!url.hostname.endsWith('.example.invalid')) throw new Error('Offline build forbids network');
  const body = JSON.parse(options.body || '{}');
  const allowed = query => /^select "slug", "updated_at" from "app"\."public_(artists|sets)" order by "public_(artists|sets)"\."slug" asc$/.test(query || '');
  const queries = body.queries || [body];
  if (!queries.every(item => allowed(item.query) && (!item.params || item.params.length === 0))) {
    throw new Error('Offline build received a query outside the synthetic sitemap fixture');
  }
  return new Response(JSON.stringify(body.queries ? queries.map(() => empty) : empty), {
    status: 200, headers: { 'content-type': 'application/json' },
  });
};
