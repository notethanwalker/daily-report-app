"use client";

import {useEffect,useMemo,useState} from "react";
import {AuthGate,type Account} from "../auth-shell";
import "./v4.css";

const API="/backend";

type LayerKey="research"|"macro"|"opportunity"|"deployment";
type Overview={version:string;pipeline:string[];layers:Record<LayerKey,any>};
type Deployment={basket:string;capital:number;eligible:any[];unavailable:any[];methodology:string;model:string};

async function getJson(url:string){
 const r=await fetch(url,{cache:"no-store",credentials:"include"});
 const d=await r.json().catch(()=>({}));
 if(!r.ok)throw new Error(d?.detail||`HTTP ${r.status}`);
 return d;
}

export default function V4(){return <AuthGate>{account=><DecisionStack account={account}/>}</AuthGate>}

function DecisionStack({account}:{account:Account}){
 const[overview,setOverview]=useState<Overview|null>(null);
 const[deployment,setDeployment]=useState<Deployment|null>(null);
 const[active,setActive]=useState<LayerKey>("research");
 const[capital,setCapital]=useState(1000);
 const[basket,setBasket]=useState("ai-buildout");
 const[loading,setLoading]=useState(true);
 const[error,setError]=useState("");
 const[deployLoading,setDeployLoading]=useState(false);

 async function load(){setLoading(true);setError("");try{setOverview(await getJson(`${API}/api/v1/stack/overview`))}catch(e:any){setError(e?.message||String(e))}finally{setLoading(false)}}
 async function loadDeployment(){setDeployLoading(true);setError("");try{setDeployment(await getJson(`${API}/api/v1/stack/deployment?basket=${encodeURIComponent(basket)}&capital=${capital}`))}catch(e:any){setError(e?.message||String(e))}finally{setDeployLoading(false)}}
 useEffect(()=>{load()},[]);
 useEffect(()=>{if(active==="deployment"&&!deployment)loadDeployment()},[active]);

 const layer=overview?.layers?.[active];
 const pipeline=useMemo(()=>[
  ["research","Research","What is happening?"],
  ["macro","Macro","Where is capital moving?"],
  ["opportunity","Opportunity","Where is the asymmetry?"],
  ["deployment","Deployment","Where should the next dollar go?"],
 ] as const,[]);

 if(loading)return <main className="v4-shell"><div className="v4-loading">Loading Daily Report v4 decision stack…</div></main>;
 return <main className="v4-shell">
  <header className="v4-header">
   <div><span className="v4-kicker">DAILY REPORT V4 · DEVELOPMENT BUILD</span><h1>Decision Stack</h1><p>Research → Macro → Opportunity → Deployment</p></div>
   <div className="v4-user"><span>{account.name}</span><small>{overview?.version||"4.0-dev"}</small></div>
  </header>
  {error&&<div className="v4-error">{error}</div>}
  <section className="v4-pipeline" aria-label="Decision pipeline">
   {pipeline.map(([key,title,question],i)=><button key={key} className={active===key?"active":""} onClick={()=>setActive(key)}><span>{i+1}</span><div><strong>{title}</strong><small>{question}</small></div></button>)}
  </section>

  {active==="research"&&<section className="v4-grid">
   <article className="v4-card hero"><span className="label">Research coverage</span><strong>{layer?.symbols??0}</strong><p>Watchlist + portfolio symbols currently feeding the decision stack.</p></article>
   <article className="v4-card"><span className="label">Stored market snapshots</span><strong>{layer?.stored_market_snapshots??0}</strong><p>Shared cached observations reused across users and layers.</p></article>
   <article className="v4-card"><span className="label">Feature snapshots</span><strong>{layer?.stored_feature_snapshots??0}</strong><p>Persisted derived features used for opportunity scoring and change detection.</p></article>
   <article className="v4-card wide"><h2>Research workspaces</h2><div className="v4-chips">{(layer?.capabilities||[]).map((x:string)=><span key={x}>{x}</span>)}</div><p className="muted">Existing Report, Markets, Portfolio, Security Research, World News, Events, Large Flow, Theses and Alerts remain part of this layer rather than being removed.</p></article>
  </section>}

  {active==="macro"&&<section className="v4-grid">
   <article className="v4-card wide"><h2>Sector leadership</h2><div className="v4-table">{(layer?.leaders||[]).map((x:any)=><div key={x.symbol}><strong>{x.symbol}</strong><span>{x.name}</span><b>{Number(x.rotation_score).toFixed(2)}</b></div>)}</div></article>
   <article className="v4-card wide"><h2>Sector weakness</h2><div className="v4-table">{(layer?.laggards||[]).map((x:any)=><div key={x.symbol}><strong>{x.symbol}</strong><span>{x.name}</span><b>{Number(x.rotation_score).toFixed(2)}</b></div>)}</div></article>
   <article className="v4-card wide"><h2>Macro model roadmap</h2><div className="v4-chips">{(layer?.capabilities||[]).map((x:string)=><span key={x}>{x}</span>)}</div><p className="muted">Next iterations will persist rotation acceleration/deceleration, transition history and confidence rather than treating sector strength as a one-snapshot heatmap.</p></article>
  </section>}

  {active==="opportunity"&&<section className="v4-grid">
   <article className="v4-card wide"><div className="section-head"><div><span className="label">Candidate funnel</span><h2>Highest current opportunity scores</h2></div><strong>{layer?.candidate_count??0} candidates</strong></div><div className="v4-table opportunities">{(layer?.candidates||[]).map((x:any)=><div key={x.symbol}><strong>{x.symbol}</strong><span>{x.sector||"Unclassified"}</span><span>100MA {x.ma100_distance==null?"—":`${Number(x.ma100_distance).toFixed(1)}%`}</span><span>W%R {x.williams_feature==null?"—":Number(x.williams_feature).toFixed(1)}</span><b>{Number(x.score).toFixed(1)}</b></div>)}</div><p className="muted">{layer?.methodology}</p></article>
  </section>}

  {active==="deployment"&&<section className="v4-grid">
   <article className="v4-card wide deployment-controls"><div><span className="label">New capital</span><h2>Williams Priority deployment</h2><p>Cross-sectional allocation only. Existing positions are not rebalanced.</p></div><div className="control-row"><select value={basket} onChange={e=>setBasket(e.target.value)}><option value="ai-buildout">AI Buildout Basket</option><option value="watchlist">Watchlist + Portfolio</option></select><label>$<input type="number" min="0" step="500" value={capital} onChange={e=>setCapital(Number(e.target.value)||0)}/></label><button onClick={loadDeployment} disabled={deployLoading}>{deployLoading?"Calculating…":"Calculate"}</button></div></article>
   {deployment&&<article className="v4-card wide"><div className="section-head"><div><span className="label">{deployment.model}</span><h2>{deployment.basket}</h2></div><strong>${Number(deployment.capital).toLocaleString()}</strong></div><div className="allocation-list">{deployment.eligible.map((x:any)=><div key={x.symbol}><div><strong>{x.priority_rank}. {x.symbol}</strong><small>14M W%R {Number(x.williams_r).toFixed(1)} · {x.signal_month}</small></div><span>{(Number(x.priority_weight)*100).toFixed(1)}%</span><b>${Number(x.suggested_dollars).toLocaleString()}</b></div>)}</div>{deployment.unavailable?.length>0&&<div className="v4-warning">Unavailable: {deployment.unavailable.map((x:any)=>`${x.symbol} (${x.reason})`).join(", ")}</div>}<p className="muted">{deployment.methodology}</p></article>}
  </section>}

  <footer className="v4-footer">Legacy Daily Report is preserved on the <code>legacy-daily-report</code> branch. This workspace is the v4 rebuild surface.</footer>
 </main>
}
