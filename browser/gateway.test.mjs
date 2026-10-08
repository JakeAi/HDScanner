import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {BrowserGateway, validateRequest} from './gateway.mjs';

const endpoint = 'https://apionline.homedepot.com/federation-gateway/graphql';
const request = {url: endpoint + '?opname=searchModel', payload: {
  operationName:'searchModel', query:'query searchModel { products }', variables:{}},
  headers: {'User-Agent':'borrowed', Cookie:'private', 'x-experience-name':'general-merchandise'}};

test('destination restriction and browser-owned headers', () => {
  assert.deepEqual(validateRequest(request, endpoint).headers, {'x-experience-name':'general-merchandise'});
  for (const url of ['http://localhost/admin', endpoint.replace('apionline.', 'evil.') + '?opname=searchModel',
    endpoint + '?opname=deleteAccount', endpoint + '?opname=searchModel&x=1']) {
    assert.throws(() => validateRequest({...request,url}, endpoint));
  }
});

test('saved scanner cooldown stops before launching or sending', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(),'hd-browser-'));
  const scannerCooldown = path.join(directory,'scanner-cooldown');
  await fs.writeFile(scannerCooldown, new Date(Date.now()+3600000).toISOString());
  const browser = {context:() => {throw new Error('Must not launch');}};
  const gateway = new BrowserGateway({browser,directory,scannerCooldown,endpoint});
  const response = await gateway.request(request);
  assert.equal(response.status,206);
  assert.equal(gateway.sent,0);
  assert.ok(Number(response.headers['retry-after'])>0);
  await fs.rm(directory,{recursive:true});
});

test('206 persists across gateway instances and prevents another browser call', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(),'hd-browser-'));
  let calls=0;
  const page = {isClosed:()=>false,on:()=>{},off:()=>{},evaluate:async()=>{
    calls++; return {status:206,body:'{}',headers:{'retry-after':'7200'}};
  }};
  const gateway = new BrowserGateway({browser:{},directory,endpoint,minDelayMs:0});
  gateway.page=page;
  assert.equal((await gateway.request(request)).status,206);
  assert.equal((await gateway.request(request)).status,206);
  const restarted = new BrowserGateway({browser:{},directory,endpoint});
  assert.equal((await restarted.request(request)).status,206);
  assert.equal(calls,1);
  assert.ok(await restarted.cooldownUntil()>Date.now()+7100000);
  await fs.rm(directory,{recursive:true});
});

test('an unreadable dispatched response stops without replay', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(),'hd-browser-'));
  const gateway = new BrowserGateway({browser:{},directory,endpoint,minDelayMs:0});
  gateway.page = {isClosed:()=>false,on:()=>{},off:()=>{},evaluate:async()=>{
    gateway.dispatched=true; throw new Error('CORS response unavailable');
  }};
  assert.equal((await gateway.request(request)).status,403);
  assert.equal((await gateway.request(request)).status,206);
  assert.ok(await gateway.cooldownUntil()>Date.now());
  await fs.rm(directory,{recursive:true});
});
