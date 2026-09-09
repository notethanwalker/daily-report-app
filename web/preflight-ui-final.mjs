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
const now=new Date().toISOString();
const report={started:now,viewports:{},errors:[],warnings:[],consoleErrors:[]};
const rotationRows=[
 {symbol:'SMH',name:'Semiconductors',state:'leading_accelerating',rotation_pressure:2.1,rotation_score:2.1,conviction:90,delta_1_observation:.4,delta_3_observations:.9,forward_bias:'current_leader'},
 {symbol:'XLK',name:'Technology',state:'leading_stable',rotation_pressure:1.3,rotation_score:1.3,conviction:82,delta_1_observation:.1,delta_3_observations:.4,forward_bias:'current_leader'},
 {symbol:'XLI',name:'Industrials',state:'recovering',rotation_pressure:.6,rotation_score:.6,conviction:68,delta_1_observation:.2,delta_3_observations:.5,forward_bias:'early_rotation_candidate'},
 {symbol:'XLV',name:'Healthcare',state:'lagging_improving',rotation_pressure:.2,rotation_score:.2,conviction:62,delta_1_observation:.3,delta_3_observations:.7,forward_bias:'watch_for_rotation'},
 {symbol:'XLY',name:'Consumer discretionary',state:'leading_weakening',rotation_pressure:-.8,rotation_score:-.8,conviction:55,delta_1_observation:-.2,delta_3_observations:-.5,forward_bias:'rotation_out_risk'},
 {symbol:'XLP',name:'Consumer staples',state:'lagging_deteriorating',rotation_pressure:-1.8,rotation_score:-1.8,conviction:78,delta_1_observation:-.4,delta_3_observations:-.9,forward_bias:'avoidance_bias'}
];
const candidates=Array.from({length:18},(_,i)=>({symbol:['AAOI','AXTI','NBIS','IONQ','OKLO','SNDK','MU','NVDA','PLTR','AMD','AVGO','MRVL','CRDO','COHR','LITE','VRT','DELL','SMCI'][i],rotation_proxy:'SMH',sector:'Technology',setup_type:i<4?'strong':i<10?'weak':'near',bucket:i<4?'strong':i<10?'weak':'near',price_vs_ma100_percent:(i%6)*1.1,williams_r_14:-88+i*3.1,verification_status:i%3===0?'verified':'primary_only',average_dollar_volume_20d:50_000_000+i*3_000_000,funnel_score:88-i*2.2}));
const flowEvents=Array.from({length:14},(_,i)=>({event_type:'options',symbol:['NVDA','AAOI','NBIS','MU','IONQ','OKLO','AMD'][i%7],provider:'SquawkFlow',outlier_score:90-i,source_url:'https://squawkflow.com/options-flow',occurred_at:new Date(Date.now()-i*35*60000).toISOString(),data:{side:i%3?'call':'put',aggression:i%2?'buy':'sell',premium:1_500_000-i*45_000,strike:100+i*5,expiration:'2026-10-16',contracts:1000+i*25,volume_oi_ratio:1.5+i*.1,market_cap:40_000_000_000}}));

function json(route,body,status=200){return route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});}
async function mock(route){
 const u=new URL(route.request().url()),p=u.pathname;
 if(p.endsWith('/api/v1/auth/session')) return json(route,{account:{id:'test',email:'test@example.com',name:'Preflight',name_required:false,role:'owner',status:'approved',enabled:true}});
 if(p.includes('/api/v1/stack/overview')) return json(route,{version:'4.10-preflight',pipeline:['research','macro','opportunity','deployment'],layers:{research:{tracked_symbols:15,stored_market_snapshots:802,stored_feature_snapshots:320},macro:{rotation_history_days:5},opportunity:{},deployment:{}}});
 if(p.includes('/api/v1/stack/research/')) return json(route,{symbol:p.split('/').pop()||'NBIS',registry:{name:'Test security',sector:'Technology'},market:{price:212.45,retrieved_at:now,provider:'Yahoo',verification_status:'verified',source_url:'https://finance.yahoo.com/'},latest_features:{buy_score:74.2,williams_r:-76.4,model_version:'v4.10'},rotation_context:{proxy:'SMH',basis:'sector',state:{state:'leading_accelerating',rotation_pressure:1.7,conviction:84,observations:8,data_age_hours:1}},flow_72h:{events:13},data_state:{market:true,fundamentals:true,feature_history_points:8},score_history:{buy_score_change:5.2,history:[1,2,3],largest_positive_drivers:[{component:'Williams',buy_score_contribution_delta:3.1}],largest_negative_drivers:[{component:'Risk',buy_score_contribution_delta:-.8}],raw_driver_changes:[{field:'williams',label:'Williams %R',delta:-7.2}]},fundamentals:{pe_ratio:31.2,price_to_sales_ratio:8.4,quarterly_revenue_growth_yoy:.42},theses:[{id:'1',title:'AI infrastructure demand',statement:'Growth remains tied to accelerated compute buildout.'}]});
 if(p.includes('/api/v1/stack/rotation')) return json(route,{rows:rotationRows,early_rotation:rotationRows.filter(x=>['early_rotation_candidate','watch_for_rotation'].includes(x.forward_bias)),outflow_risk:rotationRows.filter(x=>['rotation_out_risk','avoidance_bias'].includes(x.forward_bias)),methodology:'Relative strength, persistence, trend and rotation state.'});
 if(p.includes('/api/v1/stack/candidates/enrich')) return json(route,{jobs_added:3});
 if(p.includes('/api/v1/stack/candidates')) return json(route,{coverage:{market_wide_ready:false,cached_snapshot_coverage_percent:9.8,registry_scannable:5679,cached_scannable:556,technical_complete:555,technical_coverage_percent:9.8,limitation:'Preflight partial coverage.'},verification:{verified:180,primary_only:375},last_cache_update:now,candidates,rows:candidates,stages:[{name:'Universe',count:5679},{name:'Cached',count:556},{name:'Technicals',count:555},{name:'Ranked',count:72}]});
 if(p.includes('/api/v1/stack/deployment')) return json(route,{basket:'ai-buildout',capital:1000,eligible:[{symbol:'NBIS',weight:.35,suggested_dollars:350,williams_r:-82,fundamental_score:{score:78,grade:'B+',coverage:4,components:{growth:86,profitability:72,valuation:65,leverage:80}}},{symbol:'AAOI',weight:.3,suggested_dollars:300,williams_r:-79,fundamental_score:{score:70,grade:'B',coverage:4,components:{growth:82,profitability:60,valuation:71,leverage:67}}},{symbol:'MU',weight:.2,suggested_dollars:200,williams_r:-74,fundamental_score:{score:81,grade:'A-',coverage:5,components:{growth:79,profitability:83,valuation:76,leverage:85}}}],unavailable:[],methodology:'Williams Priority',model:'Williams Priority v1 + informational fundamentals',fundamental_score_policy:'informational_only'});
 if(p.includes('/api/v1/flow/recent')) return json(route,{provider:'SquawkFlow',events:flowEvents,stored_events:flowEvents,history_count:flowEvents.length});
 if(p.includes('/api/v1/flow/analytics')) return json(route,{rows:[{symbol:'NVDA',flow_to_market_cap:.00014,flow_to_daily_dollar_volume:.003,total_premium:4200000,premium_1h:800000,premium_24h:3200000,premium_72h:4200000,unique_contracts:4,events:5},{symbol:'AAOI',flow_to_market_cap:.0018,flow_to_daily_dollar_volume:.021,total_premium:1700000,premium_1h:300000,premium_24h:1200000,premium_72h:1700000,unique_contracts:3,events:4}]});
 if(p.includes('/api/v1/portfolios')) return json(route,{portfolios:[]});
 if(p.includes('/api/v1/events')) return json(route,{events:[],items:[]});
 if(p.includes('/api/v1/news')||p.includes('/world-news')) return json(route,{items:[],articles:[],topics:[]});
 if(p.includes('/api/v1/system')||p.includes('/health')) return json(route,{status:'ok',rows:[],items:[]});
 if(p.includes('/api/v1/auth/admin/pending')) return json(route,{accounts:[{id:'p1',email:'pending@example.com',created_at:now}]});
 if(p.includes('/api/v1/auth/')) return json(route,{account:{id:'test',email:'test@example.com',name:'Preflight',name_required:false,role:'owner',status:'approved',enabled:true},message:'ok'});
 return json(route,{rows:[],items:[],events:[],positions:[],accounts:[],symbols:[],data:[],status:'ok'});
}

async function auditLayout(page,label){return page.evaluate(label=>{
 const viewportW=document.documentElement.clientWidth,badOverflow=[];
 for(const el of [...document.querySelectorAll('button,a,select,input,[role="tab"]')]){const r=el.getBoundingClientRect();if(!r.width||!r.height)continue;if(r.left<-1||r.right>viewportW+1)badOverflow.push({tag:el.tagName,text:(el.textContent||el.getAttribute('aria-label')||'').trim().slice(0,70),left:r.left,right:r.right,viewportW});}
 const controls=[...document.querySelectorAll('button,a,select,input,[role="tab"]')].filter(el=>{const r=el.getBoundingClientRect();return r.width>0&&r.height>0});const overlaps=[];
 for(let i=0;i<controls.length;i++)for(let j=i+1;j<controls.length;j++){const a=controls[i],b=controls[j];if(a.contains(b)||b.contains(a))continue;const ra=a.getBoundingClientRect(),rb=b.getBoundingClientRect();if(ra.left<rb.right-2&&ra.right>rb.left+2&&ra.top<rb.bottom-2&&ra.bottom>rb.top+2){const sa=getComputedStyle(a),sb=getComputedStyle(b);if(sa.position==='absolute'||sb.position==='absolute')continue;overlaps.push({a:(a.textContent||a.getAttribute('aria-label')||a.tagName).trim().slice(0,50),b:(b.textContent||b.getAttribute('aria-label')||b.tagName).trim().slice(0,50)});if(overlaps.length>=30)break;}}
 return {label,badOverflow,overlaps,scrollWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth};
},label)}
async function safeClick(locator,label,out){try{if(await locator.count()&&await locator.first().isVisible()){await locator.first().click({timeout:3500});await locator.first().page().waitForTimeout(80);out.interactions.push(label);return true}}catch(e){out.failures.push({label,error:String(e).slice(0,250)})}return false}

const browser=await chromium.launch({headless:true});
for(const vp of viewports){
 const context=await browser.newContext({viewport:{width:vp.width,height:vp.height}});await context.route('**/backend/**',mock);const page=await context.newPage();
 const out={layout:[],interactions:[],failures:[],pageErrors:[],consoleErrors:[]};report.viewports[vp.name]=out;
 page.on('pageerror',e=>out.pageErrors.push(String(e)));page.on('console',m=>{if(m.type()==='error')out.consoleErrors.push(m.text())});
 await page.goto(BASE+'/v4',{waitUntil:'networkidle'});await page.getByRole('heading',{name:'Decision Stack',exact:true}).waitFor({timeout:10000});out.layout.push(await auditLayout(page,'research-initial'));
 await page.getByLabel('Ticker').fill('NBIS');await safeClick(page.getByRole('button',{name:'Open',exact:true}),'research:open',out);out.layout.push(await auditLayout(page,'research-populated'));
 for(const layer of ['Macro','Opportunity','Deployment','Research']){
   const button=page.locator('.v4-pipeline button').filter({hasText:layer});await safeClick(button,`layer:${layer}`,out);await page.waitForTimeout(150);out.layout.push(await auditLayout(page,layer.toLowerCase()));
   if(layer==='Macro'){for(const n of ['Rotation pressure','Conviction','Ticker'])await safeClick(page.getByRole('button',{name:new RegExp(n,'i')}),`macro-sort:${n}`,out);for(const sel of ['View','Rank metric']){const x=page.getByLabel(sel);if(await x.count()){const opts=await x.locator('option').evaluateAll(os=>os.map(o=>o.value));for(const v of opts.slice(0,5)){try{await x.selectOption(v)}catch{}}}}}
   if(layer==='Opportunity'){for(const n of ['Opportunity score','Williams %R','100MA distance','20D dollar volume','Ticker'])await safeClick(page.getByRole('button',{name:new RegExp(n,'i')}),`opp-sort:${n}`,out);const first=page.locator('.table-row-button').first();await safeClick(first,'opportunity:drillthrough',out)}
   if(layer==='Deployment'){const selects=page.locator('select');for(let i=0;i<await selects.count();i++){const s=selects.nth(i);if(await s.isVisible()){const opts=await s.locator('option').count();if(opts>1)try{await s.selectOption({index:1})}catch{}}}for(const re of [/refresh/i,/calculate/i,/update/i])await safeClick(page.getByRole('button',{name:re}),`deployment:${re}`,out)}
 }
 const deepPaths=['portfolio','events','flow','data-health','world-news'];
 for(const d of deepPaths){await page.goto(`${BASE}/v4/deep/${d}`,{waitUntil:'networkidle'});await page.waitForTimeout(120);out.interactions.push(`deep:${d}`);out.layout.push(await auditLayout(page,`deep:${d}`));
   if(d==='flow'){for(const tab of ['Feed','Relative Flow','Persistence','Methodology']){await safeClick(page.getByRole('tab',{name:tab,exact:true}),`flow:${tab}`,out);out.layout.push(await auditLayout(page,`flow:${tab}`))}for(const n of ['Ticker','Premium','Strike','Expiration','Contracts','Observed'])await safeClick(page.getByRole('button',{name:new RegExp(`^${n}`)}),`flow-sort:${n}`,out)}
   if(d==='portfolio'){for(const tab of ['Overview','Holdings','Risk','History','Manage'])await safeClick(page.getByRole('tab',{name:tab,exact:true}),`portfolio:${tab}`,out)}
 }
 for(const l of out.layout){if(l.badOverflow.length)report.errors.push({viewport:vp.name,type:'control-overflow',detail:l});if(l.overlaps.length)report.errors.push({viewport:vp.name,type:'control-overlap',detail:l});if(l.scrollWidth>l.clientWidth+2)report.errors.push({viewport:vp.name,type:'document-horizontal-scroll',detail:l})}
 for(const f of out.failures)report.errors.push({viewport:vp.name,type:'interaction',detail:f});for(const e of out.pageErrors)report.errors.push({viewport:vp.name,type:'pageerror',detail:e});for(const e of out.consoleErrors)report.consoleErrors.push({viewport:vp.name,error:e});
 await page.goto(BASE+'/v4',{waitUntil:'networkidle'});await page.screenshot({path:`preflight-final-${vp.name}.png`,fullPage:true});await context.close();
}
await browser.close();report.finished=new Date().toISOString();fs.writeFileSync('preflight-final-report.json',JSON.stringify(report,null,2));console.log(JSON.stringify({errors:report.errors.length,consoleErrors:report.consoleErrors.length,viewports:Object.keys(report.viewports),interactions:Object.fromEntries(Object.entries(report.viewports).map(([k,v])=>[k,v.interactions.length]))},null,2));if(report.errors.length||report.consoleErrors.length)process.exitCode=2;
