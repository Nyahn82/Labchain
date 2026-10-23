// Browser UI states use explicit synthetic response overrides; no live Fabric mutations.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const dir=process.env.RHU_BROWSER_TOOLS;assert(dir?.startsWith('/tmp/rhu-scan-'));
const {chromium}=await import(pathToFileURL(dir+'/node_modules/playwright/index.mjs').href);
const fixture=JSON.parse(fs.readFileSync(dir+'/fixture.json'));
const browser=await chromium.launch({channel:'chromium'});
const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:390,height:844}});
const page=await context.newPage();const checks=[];
try {
 const response=await context.request.get('https://localhost:5443/api/v1/verify/'+fixture.token);assert.equal(response.status(),200);const original=await response.json();
 for(const [status,peerState,label] of [['FOUR_PEER_VERIFIED','VERIFIED','FOUR-PEER VERIFIED'],['PARTIAL','OFFLINE','PARTIAL VERIFICATION — 3/4'],['PARTIAL','LAGGING','PEER LAGGING'],['CONFLICT','CONFLICT','CONSISTENCY CONFLICT'],['FAILED','FAILED','VERIFICATION FAILED'],['UNAVAILABLE','OFFLINE','VERIFICATION UNAVAILABLE']]) {
  const data=structuredClone(original),now=new Date().toISOString();data.blockchain_evidence=status;data.blockchain_checked_at=now;
  data.blockchain_peers.forEach((p,i)=>{p.checked_at=now;p.status=status==='UNAVAILABLE'||i===3?peerState:'VERIFIED';});data.blockchain_verified_count=data.blockchain_peers.filter(p=>p.status==='VERIFIED').length;
  await page.route('**/api/v1/verify/'+fixture.token,route=>route.fulfill({json:data}));
  await page.goto('https://localhost:5443/#/verify/'+fixture.token);await page.reload();await page.getByText(label,{exact:true}).waitFor();
  assert.equal(await page.getByRole('heading',{name:'Verified document match',exact:true}).count(),0);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.addScriptTag({path:'/tmp/rhu-ui-a11y/node_modules/axe-core/axe.min.js'});
  const a11y=await page.evaluate(async()=> (await axe.run(document.querySelector('main'),{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}})).violations.map(v=>({id:v.id,impact:v.impact,count:v.nodes.length})));
  assert.deepEqual(a11y,[]);checks.push({status,peerState,viewport:390,a11y_violations:0});
  await page.screenshot({path:dir+'/state-'+status.toLowerCase()+'-'+peerState.toLowerCase()+'.png',fullPage:true});
  await page.getByRole('button',{name:'Scan Again',exact:true}).click();await page.getByRole('button',{name:'Start Camera',exact:true}).waitFor();await page.waitForFunction(()=>document.querySelector('.qr-scanner button')===document.activeElement);
  await page.unroute('**/api/v1/verify/'+fixture.token);
 }
 fs.writeFileSync(dir+'/state-browser-evidence.json',JSON.stringify({mode:'isolated browser with explicit synthetic state overrides',checks},null,2));console.log(JSON.stringify(checks));
} finally {await browser.close();}
