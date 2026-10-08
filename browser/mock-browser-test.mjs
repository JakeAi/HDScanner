// Real headed browser against a local fixture server. No retailer requests.
import http from 'node:http';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import {BrowserSession} from './browser-session.mjs';
import {BrowserGateway} from './gateway.mjs';

let received = 0;
const fixture = http.createServer(async (req, res) => {
  if (req.method === 'POST') {
    received++;
    let data=''; for await (const chunk of req) data+=chunk;
    assert.equal(JSON.parse(data).operationName,'storeSearch');
    res.writeHead(206, {'Content-Type':'application/json', 'Retry-After':'3600'});
    return res.end('{"data":null}');
  }
  res.writeHead(200, {'Content-Type':'text/html'});
  res.end('<html><title>HDScanner local browser fixture</title><body>Local test</body></html>');
});
await new Promise(resolve => fixture.listen(0,'127.0.0.1',resolve));
const directory='/browser-data/mock-test';
await fs.mkdir(directory,{recursive:true});
const home=`http://127.0.0.1:${fixture.address().port}/`;
const endpoint=home+'federation-gateway/graphql';
const browser=new BrowserSession(directory,{headless:false,sandbox:true,profile:'local-test'});
const gateway=new BrowserGateway({browser,directory,endpoint,home,minDelayMs:0});
try {
  const response=await gateway.request({url:endpoint+'?opname=storeSearch',
    payload:{operationName:'storeSearch',query:'query storeSearch { stores }',variables:{}},
    headers:{'Content-Type':'application/json'}});
  assert.equal(response.status,206);
  assert.equal(response.headers['retry-after'],'3600');
  assert.equal(JSON.parse(response.body).data,null);
  await gateway.request({url:endpoint+'?opname=storeSearch',
    payload:{operationName:'storeSearch',query:'query storeSearch { stores }',variables:{}},headers:{}});
  assert.equal(received,1);
  console.log('PASS:',process.env.HD_BROWSER_ENGINE,'headed browser, sandbox, JSON, Retry-After and persistent cooldown; fixture requests:',received);
} finally {await gateway.close(); await new Promise(resolve=>fixture.close(resolve));}
