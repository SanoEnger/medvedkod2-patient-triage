import assert from 'node:assert/strict';
import test from 'node:test';
import worker, {handle} from './worker.mjs';

const env = {CORE_RELAY_TOKEN:'synthetic-relay-' + 'x'.repeat(40), CORE_SERVICE_TOKEN:'synthetic-service'};
const request = (body = {token:'synthetic+jwt'}, secret = env.CORE_RELAY_TOKEN) => new Request('https://relay.example/resolve', {
  method:'POST', headers:{Authorization:'Bearer '+secret, 'Content-Type':'application/json'}, body:JSON.stringify(body),
});

test('Cloudflare execution context is not treated as a fetch implementation', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => Response.json({_id:'synthetic-id'});
  try {
    assert.equal((await worker.fetch(request(),env,{waitUntil(){}})).status,200);
  } finally { globalThis.fetch = original; }
});

test('authenticates relay, forwards correct contract, discards personal fields', async () => {
  const response = await handle(request(), env, async (url, options) => {
    assert.equal(url.origin, 'https://tm-test-yakut.hostco.ru');
    assert.equal(url.searchParams.get('token'), 'synthetic+jwt');
    assert.equal(options.headers.Authorization, 'Bearer synthetic-service');
    assert.equal(options.redirect, 'manual');
    return Response.json({_id:'synthetic-id', SNILS:'private', phone:'private'});
  });
  assert.equal(response.status,200);
  assert.equal(response.headers.get('Cache-Control'),'no-store');
  assert.deepEqual(await response.json(),{_id:'synthetic-id'});
});

test('unauthorized requests never reach Core', async () => {
  const r = await handle(request(undefined,'incorrect'),env,()=>assert.fail('must not contact Core'));
  assert.equal(r.status,401);
});

test('missing configuration fails closed', async () => {
  assert.equal((await handle(request(),{},()=>assert.fail())).status,503);
});

test('oversized body and arbitrary destination are rejected', async () => {
  assert.equal((await handle(request({token:'x'.repeat(9000)}),env,()=>assert.fail())).status,413);
  assert.equal((await handle(request({token:'x',url:'https://other.example'}),env,()=>assert.fail())).status,422);
});

for (const [status, expected] of [[302,503],[401,401],[404,401],[403,503],[500,503]]) {
  test(`Core ${status} never grants an identity`, async () => {
    const response = await handle(request(),env,async()=>new Response('private upstream error',{status}));
    assert.equal(response.status,expected);
    assert.equal((await response.text()).includes('private'),false);
  });
}

test('malformed Core profile and network errors fail closed', async () => {
  assert.equal((await handle(request(),env,async()=>Response.json({SNILS:'private'}))).status,503);
  const response=await handle(request(),env,async()=>{throw new Error('URL containing private token');});
  assert.equal(response.status,503);
  assert.equal((await response.text()).includes('private'),false);
});
