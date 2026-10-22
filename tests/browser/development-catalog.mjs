// Existing UI, isolated SQLite, unreviewed active catalog. No clinical approval.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const tools=process.env.RHU_BROWSER_TOOLS, dir=process.env.RHU_CATALOG_FIXTURE;
assert(tools?.startsWith('/tmp/rhu-scan-') && dir?.startsWith('/tmp/rhu-scan-'));
const {chromium}=await import(pathToFileURL(tools+'/node_modules/playwright/index.mjs').href);
const browser=await chromium.launch({headless:true,channel:'chromium'});
const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1280,height:900}});
const page=await context.newPage(), errors=[], evidence=[];
page.on('pageerror',e=>errors.push(e.message));
const base='https://localhost:5443';
try {
 await page.goto(base+'/#/login');
 await page.getByLabel('Username',{exact:true}).fill('tester');
 await page.getByLabel('Password',{exact:true}).fill('Synthetic-password-123!');
 await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await page.waitForURL('**/#/dashboard');
 for(const name of ['CBC with Differential Panel','Routine Urinalysis Panel','Routine Fecalysis Panel','Lipid Profile']) {
  await page.goto(base+'/#/orders/new?patient_id=1');
  await page.getByLabel('Catalog entries',{exact:true}).selectOption('panels');
  await page.getByRole('searchbox',{name:'Find examinations'}).fill(name);
  const box=page.getByRole('checkbox',{name:'Select '+name,exact:true});
  await box.waitFor(); assert(await box.isEnabled()); await box.check();
  const posted=page.waitForResponse(r=>r.url().endsWith('/api/v1/lab-orders')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Create order',exact:true}).click();
  const response=await posted;assert.equal(response.status(),201); const order=await response.json();
  assert(order.items.length>0);
  assert(order.items.every(i=>i.definition_snapshot.test.facility_status==='UNREVIEWED'));
  await page.waitForURL('**/#/orders/'+order.order_id);await page.reload();
  await page.getByRole('heading',{name:'Ordered examinations and specimen requirements'}).waitFor();
  const samples=new Map();
  for(const item of order.items){const sp=item.definition_snapshot.specimens[0];samples.set(sp.sample_type_id,sp.sample_name);}
  for(const [id,sample] of samples){
   await page.goto(base+`/#/orders/${order.order_id}/specimens`);
   await page.getByRole('button',{name:'Register specimen',exact:true}).click();
   const dialog=page.getByRole('dialog');
   await dialog.getByRole('searchbox',{name:'Search sample type'}).fill(sample);
   await dialog.getByRole('combobox',{name:'Sample type *'}).selectOption(String(id));
   const boxes=dialog.getByRole('checkbox');let count=0;
   for(let i=0;i<await boxes.count();i++) if(await boxes.nth(i).isEnabled()){await boxes.nth(i).check();count++;}
   assert(count>0);
   const registered=page.waitForResponse(r=>r.url().endsWith(`/lab-orders/${order.order_id}/specimens`)&&r.request().method()==='POST');
   await dialog.getByRole('button',{name:'Register specimen',exact:true}).click();
   assert.equal((await registered).status(),201);await dialog.waitFor({state:'hidden'});
  }
  evidence.push({panel:name,items:order.items.length,specimens:[...samples.values()],saved:true,facility_status:'UNREVIEWED'});
 }
 await page.goto(base+'/#/orders/new?patient_id=1');
 await page.getByRole('searchbox',{name:'Find examinations'}).fill('Hemoglobin');
 const hemoglobin=page.getByRole('checkbox',{name:'Select Hemoglobin',exact:true});
 await hemoglobin.waitFor();assert(await hemoglobin.isEnabled());await hemoglobin.check();
 const posted=page.waitForResponse(r=>r.url().endsWith('/api/v1/lab-orders')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'Create order',exact:true}).click();assert.equal((await posted).status(),201);
 await page.waitForURL(/#\/orders\/\d+$/);
 evidence.push({test:'Hemoglobin',saved:true,facility_status:'UNREVIEWED'});
 await page.screenshot({path:dir+'/development-order-saved.png',fullPage:true});
 assert.deepEqual(errors,[]);
 fs.writeFileSync(dir+'/browser-evidence.json',JSON.stringify({scope:'Isolated synthetic data; unchanged deployed frontend',checks:evidence},null,2));
 console.log(JSON.stringify(evidence,null,2));
} catch(e) {await page.screenshot({path:dir+'/failure.png',fullPage:true});throw e;}
finally {await browser.close();}
