const CORE_ENDPOINT = 'https://tm-test-yakut.hostco.ru/api/v3/users/user-for-external-service';
const encoder = new TextEncoder();

function reply(status, data) {
  return Response.json(data, {status, headers: {'Cache-Control': 'no-store'}});
}

async function authorized(header, secret) {
  if (!header || header.length > 512) return false;
  // Compare fixed-length digests without exposing a matching secret prefix.
  const [expected, actual] = await Promise.all([
    crypto.subtle.digest('SHA-256', encoder.encode('Bearer ' + secret)),
    crypto.subtle.digest('SHA-256', encoder.encode(header)),
  ]);
  const a = new Uint8Array(expected), b = new Uint8Array(actual);
  let difference = 0;
  for (let i = 0; i < a.length; i++) difference |= a[i] ^ b[i];
  return difference === 0;
}

async function readLimited(source, limit) {
  const reader = source.body?.getReader();
  if (!reader) throw new Error('empty_body');
  let size = 0;
  const chunks = [];
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      size += value.length;
      if (size > limit) {
        await reader.cancel();
        throw new Error('body_too_large');
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return JSON.parse(new TextDecoder().decode(bytes));
}

export async function handle(request, env, fetchCore = fetch) {
  const path = new URL(request.url).pathname;
  if (path === '/health' && request.method === 'GET') return reply(200, {status:'ok'});
  if (path !== '/resolve') return reply(404, {detail:'not_found'});
  if (request.method !== 'POST') return reply(405, {detail:'method_not_allowed'});
  if (typeof env.CORE_RELAY_TOKEN !== 'string' || env.CORE_RELAY_TOKEN.length < 32 || !env.CORE_SERVICE_TOKEN) {
    return reply(503, {detail:'relay_not_configured'});
  }
  if (!await authorized(request.headers.get('Authorization'), env.CORE_RELAY_TOKEN)) {
    return reply(401, {detail:'relay_unauthorized'});
  }
  if (!request.headers.get('Content-Type')?.toLowerCase().startsWith('application/json')) {
    return reply(415, {detail:'json_required'});
  }
  let body;
  try { body = await readLimited(request, 8192); }
  catch (error) { return reply(error.message === 'body_too_large' ? 413 : 400, {detail:'invalid_request'}); }
  if (!body || typeof body !== 'object' || Object.keys(body).length !== 1
      || typeof body.token !== 'string' || !body.token.length || body.token.length > 6000) {
    return reply(422, {detail:'invalid_request'});
  }
  const url = new URL(CORE_ENDPOINT);
  url.searchParams.set('token', body.token);
  try {
    const response = await fetchCore(url, {
      method:'GET', redirect:'error', signal:AbortSignal.timeout(4000),
      headers:{Authorization:'Bearer ' + env.CORE_SERVICE_TOKEN, Accept:'application/json'},
    });
    if (response.status !== 200) {
      await response.body?.cancel();
      if ([401,404].includes(response.status)) return reply(401, {detail:'invalid_host_token'});
      return reply(503, {detail:response.status === 403 ? 'host_service_unauthorized' : 'host_auth_unavailable'});
    }
    const profile = await readLimited(response, 16384);
    if (typeof profile?._id !== 'string' || !profile._id.length || profile._id.length > 128) {
      return reply(503, {detail:'host_auth_invalid_response'});
    }
    return reply(200, {_id:profile._id});
  } catch {
    // Do not log exception messages: upstream URLs contain the launch JWT.
    return reply(503, {detail:'host_auth_unavailable'});
  }
}

export default {fetch(request, env) { return handle(request, env); }};
