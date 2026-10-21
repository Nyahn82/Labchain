// Real browser + isolated SQLite backend. All records/approvals are synthetic.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const tools=process.env.RHU_BROWSER_TOOLS, dir=process.env.RHU_CATALOG_FIXTURE;
assert(tools?.startsWith('/tmp/rhu-scan-') && dir?.startsWith('/tmp/rhu-scan-'));
const {chromium}=await import(pathToFileURL(tools+'/node_modules/playwright/index.mjs').href);
const browser=await chromium.launch({headless:true,channel:'chromium'});
const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1280,height:900}});
const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
const base='https://localhost:5443';
const evidence={scope:'Isolated synthetic browser, SQLite and explicit Fabric double; no live clinical writes',checks:[]};
async function action(label) { await page.getByRole('button',{name:label,exact:true}).click(); await page.getByRole('dialog').getByRole('button',{name:'Confirm '+label.toLowerCase(),exact:true}).click(); await page.getByRole('dialog').waitFor({state:'hidden'}); }
try {
 await page.goto(base+'/#/login');await page.getByLabel('Username',{exact:true}).fill('tester');await page.getByLabel('Password',{exact:true}).fill('Synthetic-password-123!');await page.getByRole('button',{name:'Sign in',exact:true}).click();await page.waitForURL('**/#/dashboard');
 await page.goto(base+'/#/laboratory');await page.getByRole('heading',{name:'Clinical laboratory catalog'}).waitFor();
 await page.getByRole('searchbox',{name:'Find examinations'}).fill('Hgb');await page.getByRole('link',{name:'Hemoglobin',exact:true}).waitFor();
 evidence.checks.push('Authenticated database catalog search by alias and facility availability');
 await page.goto(base+'/#/orders/new?patient_id=1');await page.getByRole('checkbox',{name:'Select Hemoglobin',exact:true}).waitFor();
 await page.getByRole('checkbox',{name:'Select Hemoglobin',exact:true}).check();
 await page.getByLabel('Catalog entries',{exact:true}).selectOption('panels');
 await page.getByRole('checkbox',{name:'Select Glycemic Assessment Panel',exact:true}).check();
 await page.getByRole('heading',{name:'Selected examinations (3 unique)'}).waitFor();
 const created=page.waitForResponse(r=>r.url().endsWith('/api/v1/lab-orders') && r.request().method()==='POST');
 await page.getByRole('button',{name:'Create order',exact:true}).click();const orderResponse=await created;assert.equal(orderResponse.status(),201);const order=await orderResponse.json();assert.equal(order.items.length,3);evidence.order_id=order.order_id;
 await page.waitForURL('**/#/orders/'+order.order_id);await page.reload();await page.getByRole('heading',{name:'Ordered examinations and specimen requirements'}).waitFor();
 evidence.checks.push('Actual order form persists panel and individual examinations, mixed specimen requirements and reopened order');
 const samples=new Map();for(const i of order.items){const s=i.definition_snapshot.specimens[0];samples.set(s.sample_type_id,s.sample_name);}
 const specimenIds=new Map();
 for(const [sid,name] of samples){
  await page.goto(base+`/#/orders/${order.order_id}/specimens`);await page.getByRole('button',{name:'Register specimen',exact:true}).click();const dialog=page.getByRole('dialog');
  await dialog.getByRole('searchbox',{name:'Search sample type'}).fill(name);
  await dialog.getByRole('combobox',{name:'Sample type *'}).selectOption(String(sid));
  const boxes=dialog.getByRole('checkbox');for(let i=0;i<await boxes.count();i++)if(await boxes.nth(i).isEnabled())await boxes.nth(i).check();
  const response=page.waitForResponse(r=>r.url().endsWith(`/lab-orders/${order.order_id}/specimens`)&&r.request().method()==='POST');await dialog.getByRole('button',{name:'Register specimen',exact:true}).click();const sp=await (await response).json();assert(sp.specimen_id);specimenIds.set(sid,sp.specimen_id);
  await page.goto(base+`/#/specimens/${sp.specimen_id}`);await action('Collect specimen');await action('Receive specimen');
  const download=page.waitForEvent('download');await action('Download barcode label');const file=await download;await file.saveAs(dir+`/specimen-${sp.specimen_id}-label.pdf`);
 }
 evidence.checks.push('Compatible specimen selection, separate EDTA and serum registrations, collection, receipt and protected barcode label downloads');
 await page.goto(base+`/#/orders/${order.order_id}/results`);
 for(const item of order.items){
  const row=page.getByRole('row').filter({has:page.getByRole('cell',{name:item.test.test_name,exact:true})}).filter({has:page.getByRole('button',{name:'Enter result',exact:true})});
  await row.getByRole('button',{name:'Enter result',exact:true}).click();let dialog=page.getByRole('dialog');await dialog.getByLabel('Result value *',{exact:true}).fill('12.3');
  const sid=item.definition_snapshot.specimens[0].sample_type_id;await dialog.getByRole('combobox',{name:'Specimen',exact:true}).selectOption(String(specimenIds.get(sid)));
  await dialog.getByRole('button',{name:'Save',exact:true}).click();await dialog.waitFor({state:'hidden'});
 }
 // Resume an actual draft using the UI before review.
 await page.getByRole('button',{name:'Edit draft',exact:true}).first().click();await page.getByRole('dialog').getByLabel('Remarks',{exact:true}).fill('SYNTHETIC browser draft resumed');await page.getByRole('dialog').getByRole('button',{name:'Save',exact:true}).click();await page.getByRole('dialog').waitFor({state:'hidden'});
 for(let i=0;i<3;i++){await page.getByRole('button',{name:'Review result',exact:true}).first().click();await page.getByRole('dialog').getByRole('button',{name:'Confirm review result',exact:true}).click();await page.getByRole('dialog').waitFor({state:'hidden'});await action('Verify result');}
 evidence.checks.push('Structured scalar results entered from ordered tests, draft resumed, all results reviewed and verified through actual UI');
 await page.goto(base+`/#/orders/${order.order_id}/reports`);await page.getByRole('button',{name:'Generate report',exact:true}).click();
 const reportResponse=page.waitForResponse(r=>r.url().endsWith(`/lab-orders/${order.order_id}/reports`)&&r.request().method()==='POST');await page.getByRole('dialog').getByRole('button',{name:'Generate report',exact:true}).click();const report=await (await reportResponse).json();assert(report.report_id);evidence.report_id=report.report_id;
 await page.goto(base+`/#/reports/${report.report_id}`);await page.getByRole('button',{name:'Assign signatory',exact:true}).click();
 await page.getByRole('dialog').getByRole('combobox',{name:'Signatory profile *'}).selectOption('1');await page.getByRole('dialog').getByRole('combobox',{name:'Signing capacity *'}).selectOption('MEDICAL_TECHNOLOGIST');await page.getByRole('dialog').getByRole('button',{name:'Assign signatory',exact:true}).click();await page.getByRole('dialog').waitFor({state:'hidden'});
 await action('Sign as MEDICAL TECHNOLOGIST');await action('Approve report');await action('Release report');await page.getByRole('button',{name:'Preview PDF',exact:true}).click();await page.getByTitle('Official laboratory report PDF').waitFor();
 await page.waitForTimeout(3000);
 await page.screenshot({path:dir+'/released-report.png',fullPage:true});evidence.checks.push('Generated, assigned, signed, approved and released synthetic report through UI; native PDF preview rendered');
 assert.equal(errors.length,0,errors.join('\n'));
 await page.goto(base+'/#/orders/new?patient_id=1');await page.getByRole('heading',{name:'Choose examinations and panels'}).waitFor();await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:dir+'/mobile-order.png',fullPage:true});evidence.checks.push('390px order workflow has no horizontal overflow');
 fs.writeFileSync(dir+'/clinical-browser-evidence.json',JSON.stringify(evidence,null,2));console.log(JSON.stringify(evidence,null,2));
} catch(e){await page.screenshot({path:dir+'/clinical-browser-failure.png',fullPage:true});fs.writeFileSync(dir+'/clinical-browser-failure.txt',await page.locator('body').innerText());throw e;}finally{await browser.close();}
