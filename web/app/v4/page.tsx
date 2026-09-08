"use client";

import {useEffect,useMemo,useState} from "react";
import {AuthGate,type Account} from "../auth-shell";
import "./v4.css";

const API="/backend";
type LayerKey="research"|"macro"|"opportunity"|"deployment";
type Overview={version:string;pipeline:string[];layers:Record<LayerKey,any>};
type Deployment={basket:string;capital:number;eligible:any[];unavailable:any[];methodology:string;model:string};

async function getJson(url:string){const r=await fetch(url,{cache:"no-store",credentials:"include"});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d?.detail||`HTTP ${r.status}`);return d}
const n=(v:any,d=1)=>v==null?"—":Number(v).toFixed(d);

export default function V4(){return <AuthGate>{account=><DecisionStack account={account}/>}</AuthGate>}

function DecisionStack({account}:{account:Account}){
 const[overview,setOverview]=useState<Overview|null>(null),[deployment,setDeployment]=useState<Deployment|null>(null),[rotation,setRotation]=useState<any>(null),[funnel,setFunnel]=useState<any>(null),[research,setResearch]=useState<any>(null);
 const[active,setActive]=useState<LayerKey>("research"),[capital,setCapital]=useState(1000),[basket,setBasket]=useState("ai-buildout"),[symbol,setSymbol]=useState("NBIS");
 const[loading,setLoading]=useState(true),[error,setError]=useState(""),[deployLoading,setDeployLoading]=useState(false),[researchLoading,setResearchLoading]=useState(false);
 async function load(){setLoading(true);setError("");try{setOverview(await getJson(`${API}/api/v1/stack/overview`))}catch(e:any){setError(e?.message||String(e))}finally{setLoading(false)}}
 async function loadDeployment(){setDeployLoading(true);setError("");try{setDeployment(await getJson(`${API}/api/v1/stack/deployment?basket=${encodeURIComponent(basket)}&capital=${capital}`))}catch(e:any){setError(e?.message||String(e))}finally{setDeployLoading(false)}}
 async function loadRotation(){if(rotation)return;try{setRotation(await getJson(`${API}/api/v1/stack/rotation`))}catch(e:any){setError(e?.message||String(e))}}
 async function loadFunnel(){if(funnel)return;try{setFunnel(await getJson(`${API}/api/v1/stack/candidates?limit=60`))}catch(e:any){setError(e?.message||String(e))}}
 async function loadResearch(){const s=symbol.trim().toUpperCase();if(!s)return;setResearchLoading(true);setError("");try{setResearch(await getJson(`${API}/api/v1/stack/research/${encodeURIComponent(s)}`));setSymbol(s)}catch(e:any){setError(e?.message||String(e))}finally{setResearchLoading(false)}}
 useEffect(()=>{load()},[]);
 useEffect(()=>{if(active==="macro")loadRotation();if(active==="opportunity")loadFunnel();if(active==="deployment"&&!deployment)loadDeployment();if(active==="research"&&!research)loadResearch()},[active]);
 const layer=overview?.layers?.[active];
 const pipeline=useMemo(()=>[["research","Research","What is happening?"],["macro","Macro","Where is capital moving?"],["opportunity","Opportunity","Where is the asymmetry?"],["deployment","Deployment","Where should the next dollar go?"]] as const,[]);
 if(loading)return <main className="v4-shell"><div className="v4-loading">Loading Daily Report v4 decision stack…</div></main>;
 return <main className="v4-shell">
  <header className="v4-header"><div><span className="v4-kicker">DAILY REPORT V4 · DEVELOPMENT BUILD</span><h1>Decision Stack</h1><p>Research → Macro → Opportunity → Deployment</p></div><div className="v4-user"><span>{account.name}</span><small>{overview?.version||"4.1-dev"}</small></div></header>
  {error&&<div className="v4-error">{error}</div>}
  <section className="v4-pipeline" aria-label="Decision pipeline">{pipeline.map(([key,title,question],i)=><button key={key} className={active===key?"active":""} onClick={()=>setActive(key)}><span>{i+1}</span><div><strong>{title}</strong><small>{question}</small></div></button>)}</section>

  {active==="research"&&<section className="v4-grid">
   <article className="v4-card hero"><span className="label">Research coverage</span><strong>{layer?.symbols??0}</strong><p>Watchlist + portfolio symbols feeding the decision stack.</p></article>
   <article className="v4-card"><span className="label">Stored market snapshots</span><strong>{layer?.stored_market_snapshots??0}</strong><p>Shared cached observations reused across layers.</p></article>
   <article className="v4-card"><span className="label">Feature snapshots</span><strong>{layer?.stored_feature_snapshots??0}</strong><p>Point-in-time score history and derived features.</p></article>
   <article className="v4-card wide research-search"><div><span className="label">Security workspace</span><h2>Unified ticker research</h2><p className="muted">Cache-first composition of market, fundamentals, macro fit, flow, theses and score history.</p></div><div className="control-row"><input value={symbol} onChange={e=>setSymbol(e.target.value.toUpperCase())} onKeyDown={e=>{if(e.key==="Enter")loadResearch()}} placeholder="Ticker"/><button onClick={loadResearch} disabled={researchLoading}>{researchLoading?"Loading…":"Open"}</button></div></article>
   {research&&<>
    <article className="v4-card"><span className="label">{research.symbol}</span><strong>{research.market?.price==null?"—":`$${n(research.market.price,2)}`}</strong><p>{research.registry?.name||research.registry?.sector||"Stored security"}</p><div className="mini-stats"><span>7D <b>{n(research.market?.seven_day_percent)}%</b></span><span>30D <b>{n(research.market?.thirty_day_percent)}%</b></span><span>100MA <b>{n(research.market?.price_vs_ma100_percent)}%</b></span></div></article>
    <article className="v4-card"><span className="label">Opportunity score</span><strong>{n(research.latest_features?.buy_score,1)}</strong><p>{research.score_history?.buy_score_change==null?"No prior point":`${research.score_history.buy_score_change>=0?"+":""}${n(research.score_history.buy_score_change,1)} since prior snapshot`}</p><div className="mini-stats"><span>W%R <b>{n(research.latest_features?.williams_r,1)}</b></span><span>Sector <b>{n(research.latest_features?.sector_score,1)}</b></span></div></article>
    <article className="v4-card"><span className="label">Sector rotation</span><strong className="small-strong">{research.sector_rotation?.state?.replaceAll("_"," ")||"Unmapped"}</strong><p>{research.sector_rotation?`${n(research.sector_rotation.rotation_pressure,2)} pressure · ${n(research.sector_rotation.conviction,0)} conviction`:"No sector proxy mapping"}</p><div className="mini-stats"><span>Flow events <b>{research.flow_72h?.events??0}</b></span></div></article>
    <article className="v4-card wide"><div className="section-head"><div><span className="label">Explainability</span><h2>Why the score moved</h2></div><strong>{research.score_history?.history?.length||0} points</strong></div><div className="driver-grid"><div><h3>Positive drivers</h3>{(research.score_history?.largest_positive_drivers||[]).map((x:any)=><div className="driver" key={x.component}><span>{x.component}</span><b>+{n(x.delta,1)}</b></div>)}{!(research.score_history?.largest_positive_drivers||[]).length&&<p className="muted">No positive component change.</p>}</div><div><h3>Negative drivers</h3>{(research.score_history?.largest_negative_drivers||[]).map((x:any)=><div className="driver" key={x.component}><span>{x.component}</span><b>{n(x.delta,1)}</b></div>)}{!(research.score_history?.largest_negative_drivers||[]).length&&<p className="muted">No negative component change.</p>}</div><div><h3>Raw changes</h3>{(research.score_history?.raw_driver_changes||[]).slice(0,5).map((x:any)=><div className="driver" key={x.field}><span>{x.label}</span><b>{x.delta==null?"—":`${x.delta>=0?"+":""}${n(x.delta,2)}`}</b></div>)}</div></div></article>
    <article className="v4-card wide"><h2>Fundamental + thesis context</h2><div className="research-context"><div className="mini-stats vertical"><span>P/E <b>{n(research.fundamentals?.pe_ratio,1)}</b></span><span>P/S <b>{n(research.fundamentals?.price_to_sales_ratio,1)}</b></span><span>Revenue growth <b>{research.fundamentals?.quarterly_revenue_growth_yoy==null?"—":`${n(Number(research.fundamentals.quarterly_revenue_growth_yoy)*100,1)}%`}</b></span></div><div>{(research.theses||[]).map((t:any)=><div className="thesis" key={t.id}><strong>{t.title}</strong><p>{t.statement}</p></div>)}{!(research.theses||[]).length&&<p className="muted">No active thesis attached to this ticker.</p>}</div></div></article>
   </>}
  </section>}

  {active==="macro"&&<section className="v4-grid">
   <article className="v4-card wide"><div className="section-head"><div><span className="label">Rotation model v4</span><h2>Leadership + transition state</h2></div><strong>{rotation?.rows?.length??layer?.sector_rows??0} groups</strong></div><div className="v4-table rotation-table">{(rotation?.leaders||layer?.leaders||[]).map((x:any)=><div key={x.symbol}><strong>{x.symbol}</strong><span>{x.name}</span><span>{String(x.state||"").replaceAll("_"," ")}</span><span>{n(x.delta_3_observations,2)}</span><b>{n(x.rotation_pressure??x.rotation_score,2)}</b></div>)}</div></article>
   <article className="v4-card"><span className="label">Early rotation</span><h2>Improving laggards</h2>{(rotation?.early_rotation||layer?.early_rotation||[]).map((x:any)=><div className="compact-row" key={x.symbol}><strong>{x.symbol}</strong><span>{x.name}</span><b>{n(x.conviction,0)}</b></div>)}</article>
   <article className="v4-card"><span className="label">Outflow risk</span><h2>Weakening leadership</h2>{(rotation?.outflow_risk||layer?.outflow_risk||[]).map((x:any)=><div className="compact-row" key={x.symbol}><strong>{x.symbol}</strong><span>{x.name}</span><b>{n(x.rotation_pressure,1)}</b></div>)}</article>
   <article className="v4-card"><span className="label">States</span><h2>Rotation breadth</h2>{Object.entries(rotation?.state_counts||layer?.state_counts||{}).map(([k,v]:any)=><div className="compact-row" key={k}><span>{k.replaceAll("_"," ")}</span><b>{v}</b></div>)}</article>
   <article className="v4-card wide"><p className="muted">{rotation?.methodology||layer?.methodology}</p></article>
  </section>}

  {active==="opportunity"&&<section className="v4-grid">
   <article className="v4-card wide"><div className="section-head"><div><span className="label">Candidate funnel</span><h2>Broad market → qualified setups</h2></div><strong>{funnel?.candidates?.length??layer?.candidate_count??0}</strong></div><div className="funnel-stages">{(funnel?.stages||[]).map((x:any,i:number)=><div key={x.name}><span>{i+1}</span><strong>{x.name}</strong><b>{x.input} → {x.output}</b><small>{x.rule}</small></div>)}</div></article>
   <article className="v4-card wide"><h2>Highest-ranked market candidates</h2><div className="v4-table opportunities funnel-table">{(funnel?.candidates||layer?.candidates||[]).slice(0,30).map((x:any)=><div key={x.symbol}><strong>{x.symbol}</strong><span>{x.sector||"Unclassified"}</span><span>{x.bucket||x.rotation_state||"tracked"}</span><span>100MA {x.price_vs_ma100_percent==null&&x.ma100_distance==null?"—":`${n(x.price_vs_ma100_percent??x.ma100_distance,1)}%`}</span><span>W%R {n(x.williams_r_14??x.williams_feature,1)}</span><span>{x.rotation_state?.replaceAll("_"," ")||"—"}</span><b>{n(x.funnel_score??x.score,1)}</b></div>)}</div><p className="muted">{funnel?.methodology||layer?.methodology}</p></article>
  </section>}

  {active==="deployment"&&<section className="v4-grid">
   <article className="v4-card wide deployment-controls"><div><span className="label">New capital</span><h2>Williams Priority deployment</h2><p>Cross-sectional allocation only. Existing positions are not rebalanced.</p></div><div className="control-row"><select value={basket} onChange={e=>setBasket(e.target.value)}><option value="ai-buildout">AI Buildout Basket</option><option value="watchlist">Watchlist + Portfolio</option></select><label>$<input type="number" min="0" step="500" value={capital} onChange={e=>setCapital(Number(e.target.value)||0)}/></label><button onClick={loadDeployment} disabled={deployLoading}>{deployLoading?"Calculating…":"Calculate"}</button></div></article>
   {deployment&&<article className="v4-card wide"><div className="section-head"><div><span className="label">{deployment.model}</span><h2>{deployment.basket}</h2></div><strong>${Number(deployment.capital).toLocaleString()}</strong></div><div className="allocation-list">{deployment.eligible.map((x:any)=><div key={x.symbol}><div><strong>{x.priority_rank}. {x.symbol}</strong><small>14M W%R {n(x.williams_r,1)} · {x.signal_month}</small></div><span>{(Number(x.priority_weight)*100).toFixed(1)}%</span><b>${Number(x.suggested_dollars).toLocaleString()}</b></div>)}</div>{deployment.unavailable?.length>0&&<div className="v4-warning">Unavailable: {deployment.unavailable.map((x:any)=>`${x.symbol} (${x.reason})`).join(", ")}</div>}<p className="muted">{deployment.methodology}</p></article>}
  </section>}
  <footer className="v4-footer">Legacy Daily Report remains preserved on <code>legacy-daily-report</code>. V4 is isolated on its rebuild branch.</footer>
 </main>
}
