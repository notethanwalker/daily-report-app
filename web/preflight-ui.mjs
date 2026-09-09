import { chromium } from 'playwright';
import fs from 'node:fs';

const BASE='http://127.0.0.1:3000';
const viewports=[
  {name:'desktop-1440',width:1440,height:1000},
  {name:'desktop-1024',width:1024,height:768},
  {name:'mobile-430',width:430,height:932},
  {name:'mobile-390',width:390,height:844},
  {name:'mobile-375',width:375,height:812},
];
const report={started:new Date().toISOString(),viewports:{},errors:[],consoleErrors:[]};
const overview={version:'4.10-preflight',pipeline:['research','macro','opportunity','deployment'],layers:{research:{tracked_symbols:15,stored_market_snapshots:802,stored_feature_snapshots:320},macro:{rotation_history_days:5},opportunity:{},deployment:{}}};
const research={symbol:'NBIS',registry:{name:'Nebius Group',sector:'Technology'},market:{price:212.45,retrieved_at:new Date().toISOString(),provider:'Yahoo',verification_status:'verified',source_url:'https://finance.yahoo.com/'},latest_features:{buy_score:74.2,williams_r:-76.4,model_version:'v4.10'},rotation_context:{proxy:'SMH',basis:'sector',state:{state:'leading_accelerating',rotation_pressure:1.7,conviction:84,observations:8,data_age_hours:1}},flow_72h:{events:3},data_state:{market:true,fundamentals:true,feature_history_points:8},score_history:{buy_score_change:5.2,history:[1,2,3],largest_positive_drivers:[{component:'Williams',buy_score_contribution_delta:3.1}],largest_negative_drivers:[{component:'Risk',buy_score_contribution_delta:-0.8}],raw_driver_changes:[{field:'williams',label:'Williams %R',delta:-7.2}]},fundamentals:{pe_ratio:31.2,price_to_sales_ratio:8.4,quarterly_revenue_growth_yoy:.42},theses:[{id:'1',title:'AI infrastructure demand',statement:'Growth remains tied to accelerated compute buildout.'}]};
const rotationRows=[
 {symbol:'SMH',name:'Semiconductors',state:'leading_accelerating',rotation_pressure:2.1,rotation_score:2.1,conviction:90,delta_1_observation:.4,delta_3_observations:.9,forward_bias:'current_leader'},
 {symbol:'XLK',name:'Technology',state:'leading_stable',rotation_pressure:1.3,rotation_score:1.3,conviction:82,delta_1_observation:.1,delta_3_observations:.4,forward_bias:'current_leader'},
 {symbol:'XLI',name:'Industrials',state:'recovering',rotation_pressure:.6,rotation_score:.6,conviction:68,delta_1_observation:.2,delta_3_observations:.5,forward_bias:'early_rotation_candidate'},
 {symbol:'XLV',name:'Healthcare',state:'lagging_improving',rotation_pressure:.2,rotation_score:.2,conviction:62,delta_1_observation:.3,delta_3_observations:.7,forward_bias:'watch_for_rotation'},
 {symbol:'XLY',name:'Consumer discretionary',state:'leading_weakening',rotation_pressure:-.8,rotation_score:-.8,conviction:55,delta_1_observation:-.2,delta_3_observations:-.5,forward_bias:'rotation_out_risk'},
 {symbol:'XLP',name:'Consumer staples',state:'lagging_deteriorating',rotation_pressure:-1.8,rotation_score:-1.8,conviction:78,delta_1_observation:-.4,delta_3_observations:-.9,forward_bias:'avoidance_bias'}
];
const rotation={rows:rotationRows,early_rotation:rotationRows.filter(x=>['early_rotation_candidate','watch_for_rotation'].includes(x.forward_bias)),outflow_risk:rotationRows.filter(x=>['rotation_out_risk','avoidance_bias'].includes(x.forward_bias)),methodology:'Relative strength, persistence, trend and rotation state.'};
const candidates=Array.from({length:18},(_,i)=>({symbol:['AAOI','AXTI','NBIS','IONQ','OKLO','SNDK','MU','NVDA','PLTR','AMD','AVGO','MRVL','CRDO','COHR','LITE','VRT','DELL','SMCI'][i],rotation_proxy:'SMH',sector:'Technology',setup_type:i<4?'strong':i<10?'weak':'near',bucket:i<4?'strong':i<10?'weak':'near',price_vs_ma100_percent:(i%6)*1.1,williams_r_14:-88+i*3.1,verification_status:i%3===0?'verified':'primary_only',average_dollar_volume_20d:50_000_000+i*3_000_000,funnel_score:88-i*2.2}));
const funnel={coverage:{market_wide_ready:false,cached_snapshot_coverage_percent:9.8,registry_scannable:5679,cached_scannable:556,technical_complete:555,technical_coverage_percent:9.8,limitation:'Preflight partial coverage.'},verification:{verified:180,primary_only:375},last_cache_update:new Date().toISOString(),candidates,rows:candidates,stages:[{name:'Universe',count:5679},{name:'Cached',count:556},{name:'Technicals',count:555},{name:'Ranked',count:72}]};
const deployment={basket:'ai-buildout',capital:1000,eligible:[{symbol:'NBIS',weight:.35,suggested_dollars:350,williams_r:-82,fundamental_score:{score:78,grade:'B+',coverage:4,components:{growth:86,profitability:72,valuation:65,leverage:80}}},{symbol:'AAOI',weight:.3,suggested_dollars:300,williams_r:-79,fundamental_score:{score:70,grade:'B',coverage:4,components:{growth:82,profitability:60,valuation:71,leverage:67}}},{symbol:'MU',weight:.2,suggested_dollars:200,williams_r:-74,fundamental_score:{score:81,grade:'A-',coverage:5,components:{growth:79,profitability:83,valuation:76,leverage:85}}}],unavailable:[],methodology:'Williams Priority',model:'Williams Priority v1 + informational fundamentals',fundamental_score_policy:'informational_only'};

function json(route,body,status=200){return route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});}
async function mock(route){
 const u=new URL(route.request().url()); const p=u.pathname;
 if(p.endsWith('/api/v1/auth/session')) return json(route,{account:{id:'test',email:'test@example.com',name:'Preflight',name_required:false,role:'owner',status:'approved',enabled:true}});
 if(p.includes('/api/v1/stack/overview')) return json(route,overview);
 if(p.includes('/api/v1/stack/research/')) return json(route,research);
 if(p.includes('/api/v1/stack/rotation')) return json(route,rotation);
 if(p.includes('/api/v1/stack/candidates/enrich')) return json(route,{jobs_added:3});
 if(p.includes('/api/v1/stack/candidates')) return json(route,funnel);
 if(p.includes('/api/v1/stack/deployment')) return json(route,deployment);
 if(p.includes('/api/v1/auth/admin/pending')) return json(route,{accounts:[{id:'p1',email:'pending@example.com',created_at:new Date().toISOString()}]});
 if(p.includes('/api/v1/auth/')) return json(route,{account:{id:'test',email:'test@example.com',name:'Preflight',name_required:false,role:'owner',status:'approved',enabled:true},message:'ok'});
 return json(route,{rows:[],items:[],events:[],positions:[],accounts:[],symbols:[],data:[],status:'ok'});
}
async function auditLayout(page,label){
 return await page.evaluate((label)=>{
  const badOverflow=[]; const viewportW=document.documentElement.clientWidth;
  for(const el of [...document.querySelectorAll('button,a,select,input,[role="tab"]')]){
   const r=el.getBoundingClientRect(); if(r.width===0||r.height===0)continue;
   if(r.left < -1 || r.right > viewportW+1) badOverflow.push({tag:el.tagName,text:(el.textContent||el.getAttribute('aria-label')||'').trim().slice(0,70),left:r.left,right:r.right,viewportW});
  }
  const controls=[...document.querySelectorAll('button,a,select,input,[role="tab"]')].filter(el=>{const r=el.getBoundingClientRect();return r.width>0&&r.height>0});
  const overlaps=[];
  for(let i=0;i<controls.length;i++) for(let j=i+1;j<controls.length;j++){
    const a=controls[i],b=controls[j]; if(a.contains(b)||b.contains(a))continue;
    const ra=a.getBoundingClientRect(), rb=b.getBoundingClientRect();
    if(ra.left < rb.right-2 && ra.right > rb.left+2 && ra.top < rb.bottom-2 && ra.bottom > rb.top+2){
      const sa=getComputedStyle(a),sb=getComputedStyle(b); if(sa.position==='absolute'||sb.position==='absolute')continue;
      overlaps.push({a:(a.textContent||a.getAttribute('aria-label')||a.tagName).trim().slice(0,50),b:(b.textContent||b.getAttribute('aria-label')||b.tagName).trim().slice(0,50)});
      if(overlaps.length>=25)break;
    }
  }
  return {label,badOverflow,overlaps,scrollWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth};
 },label);
}
async function clickIfVisible(locator){try{if(await locator.isVisible()){await locator.click({timeout:2500});await locator.page().waitForTimeout(80);return true}}catch{}return false;}

const browser=await chromium.launch({headless:true});
for(const vp of viewports){
 const context=await browser.newContext({viewport:{width:vp.width,height:vp.height}});
 await context.route('**/backend/**',mock);
 const page=await context.newPage(); const errs=[]; const consoles=[];
 page.on('pageerror',e=>errs.push(String(e)));
 page.on('console',m=>{if(m.type()==='error')consoles.push(m.text())});
 const out={screens:[],layout:[],interactions:[],pageErrors:errs,consoleErrors:consoles}; report.viewports[vp.name]=out;
 await page.goto(BASE+'/v4',{waitUntil:'networkidle'});
 await page.getByRole('heading',{name:'Decision Stack',exact:true}).waitFor({timeout:10000});
 out.layout.push(await auditLayout(page,'research'));
 await page.getByLabel('Ticker').fill('NBIS'); await page.getByRole('button',{name:'Open'}).click(); await page.waitForTimeout(100);
 for(const name of ['Macro','Opportunity','Deployment','Research']){
  await page.getByRole('button',{name:new RegExp(`^${name}`)}).click(); await page.waitForTimeout(180);
  out.interactions.push(`layer:${name}`); out.layout.push(await auditLayout(page,name.toLowerCase()));
  if(name==='Macro'){
   for(const n of ['Rotation pressure','Conviction','1-observation change','3-observation change','Ticker']) await clickIfVisible(page.getByRole('button',{name:new RegExp(n)}).first());
   const view=page.getByLabel('View'); if(await view.count()) for(const v of ['leaders','early','outflow','all']){await view.selectOption(v);await page.waitForTimeout(40)}
   const rank=page.getByLabel('Rank metric'); if(await rank.count()) for(const v of ['pressure','conviction','delta1','delta3','symbol']){await rank.selectOption(v);await page.waitForTimeout(40)}
  }
  if(name==='Opportunity'){
   for(const n of ['Opportunity score','Williams %R','100MA distance','20D dollar volume','Ticker']) await clickIfVisible(page.getByRole('button',{name:new RegExp(n)}).first());
   const setup=page.getByLabel('Setup'); if(await setup.count()) for(const v of ['all','strong','weak','near']){try{await setup.selectOption(v);await page.waitForTimeout(40)}catch{}}
   const sort=page.getByLabel('Sort'); if(await sort.count()) for(const v of ['score','williams','ma100','liquidity','symbol']){await sort.selectOption(v);await page.waitForTimeout(40)}
   const first=page.locator('.opportunities .table-row-button').first(); if(await first.count()){await first.click();await page.waitForTimeout(100);out.interactions.push('opportunity:drillthrough')}
  }
  if(name==='Deployment'){
   const selects=page.locator('select'); for(let i=0;i<await selects.count();i++){const s=selects.nth(i); if(await s.isVisible()){const opts=await s.locator('option').all(); if(opts.length>1)try{await s.selectOption({index:Math.min(1,opts.length-1)})}catch{}}}
   const buttons=page.locator('button'); for(let i=0;i<await buttons.count();i++){const b=buttons.nth(i);const txt=(await b.innerText().catch(()=>'' )).trim();if(/refresh|calculate|update|apply/i.test(txt))await clickIfVisible(b)}
  }
 }
 await page.getByRole('button',{name:/Research/}).click(); await page.waitForTimeout(80);
 const hrefs=await page.locator('a[href^="/v4/deep/"]').evaluateAll(as=>[...new Set(as.map(a=>a.getAttribute('href')).filter(Boolean))]);
 for(const href of hrefs){await page.goto(BASE+href,{waitUntil:'networkidle'});out.interactions.push(`deep:${href}`);out.layout.push(await auditLayout(page,href));}
 for(const l of out.layout){if(l.badOverflow.length) report.errors.push({viewport:vp.name,type:'overflow',detail:l});if(l.overlaps.length)report.errors.push({viewport:vp.name,type:'overlap',detail:l});if(l.scrollWidth>l.clientWidth+2)report.errors.push({viewport:vp.name,type:'horizontal-scroll',detail:l});}
 report.consoleErrors.push(...consoles.map(x=>({viewport:vp.name,error:x}))); report.errors.push(...errs.map(x=>({viewport:vp.name,type:'pageerror',detail:x})));
 await page.goto(BASE+'/v4',{waitUntil:'networkidle'}); await page.screenshot({path:`preflight-${vp.name}.png`,fullPage:true});out.screens.push(`preflight-${vp.name}.png`);
 await context.close();
}
await browser.close();
report.finished=new Date().toISOString();
fs.writeFileSync('preflight-report.json',JSON.stringify(report,null,2));
console.log(JSON.stringify({errors:report.errors.length,consoleErrors:report.consoleErrors.length,viewports:Object.keys(report.viewports),report:'preflight-report.json'},null,2));
if(report.errors.length||report.consoleErrors.length) process.exitCode=2;
