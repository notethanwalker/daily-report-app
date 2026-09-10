"use client";

import {useEffect,useMemo,useState} from "react";

const API="/backend";
const DEFAULT={williams:60,ma100_proximity:30,ma100_slope:5,approach_velocity:5};
type CriteriaMap=Record<string,number>;
type SortKey="score"|"williams"|"ma100_proximity"|"ma100_slope"|"approach_velocity"|"liquidity"|"symbol";

async function api(path:string,init?:RequestInit){
 const r=await fetch(`${API}${path}`,{credentials:"include",cache:"no-store",...init,headers:{"content-type":"application/json",...(init?.headers||{})}});
 const d=await r.json().catch(()=>({}));
 if(!r.ok)throw new Error(d?.detail||`HTTP ${r.status}`);
 return d;
}
const n=(v:any,d=1)=>v==null?"—":Number(v).toFixed(d);
const money=(v:any)=>v==null?"—":Number(v)>=1e9?`$${(Number(v)/1e9).toFixed(1)}B`:Number(v)>=1e6?`$${(Number(v)/1e6).toFixed(1)}M`:`$${Number(v).toLocaleString()}`;

export default function OpportunityFormulaBuilderV4({onOpen}:{onOpen:(symbol:string)=>void}){
 const[catalog,setCatalog]=useState<any[]>([]),[criteria,setCriteria]=useState<CriteriaMap>(DEFAULT),[rows,setRows]=useState<any[]>([]),[meta,setMeta]=useState<any>(null),[presets,setPresets]=useState<any[]>([]);
 const[loading,setLoading]=useState(true),[error,setError]=useState(""),[addKey,setAddKey]=useState(""),[saveName,setSaveName]=useState(""),[expanded,setExpanded]=useState<string|null>(null);
 const[sortKey,setSortKey]=useState<SortKey>("score"),[sortDir,setSortDir]=useState<"asc"|"desc">("desc");

 async function loadPresets(){const d=await api("/api/v1/opportunities/formulas");setPresets([d.default,...(d.saved||[])]);}
 async function run(next:CriteriaMap=criteria){setLoading(true);setError("");try{const d=await api("/api/v1/opportunities/index?limit=500",{method:"POST",body:JSON.stringify({criteria:next})});setRows(d.rows||[]);setMeta(d)}catch(e:any){setError(e?.message||String(e))}finally{setLoading(false)}}
 useEffect(()=>{(async()=>{try{const[c,p]=await Promise.all([api("/api/v1/opportunities/criteria"),api("/api/v1/opportunities/formulas")]);setCatalog(c.criteria||[]);setPresets([p.default,...(p.saved||[])]);setCriteria(c.default_formula?.criteria||DEFAULT);await run(c.default_formula?.criteria||DEFAULT)}catch(e:any){setError(e?.message||String(e));setLoading(false)}})()},[]);

 const activeKeys=Object.keys(criteria);
 const available=catalog.filter(c=>!activeKeys.includes(c.key));
 const effective=useMemo(()=>{const total=Object.values(criteria).reduce((a,b)=>a+Number(b||0),0);return Object.fromEntries(Object.entries(criteria).map(([k,v])=>[k,total?Number(v)/total*100:0]))},[criteria]);
 const labelFor=(key:string)=>catalog.find(c=>c.key===key)?.label||key;
 const sorted=useMemo(()=>[...rows].sort((a,b)=>{let av:any,bv:any;if(sortKey==="score"){av=a.score;bv=b.score}else if(sortKey==="symbol"){av=a.symbol;bv=b.symbol}else if(sortKey==="liquidity"){av=a.average_dollar_volume_20d;bv=b.average_dollar_volume_20d}else{av=a.raw_criteria?.[sortKey];bv=b.raw_criteria?.[sortKey]}if(av==null&&bv==null)return 0;if(av==null)return 1;if(bv==null)return-1;const d=typeof av==="string"?String(av).localeCompare(String(bv)):Number(av)-Number(bv);return sortDir==="asc"?d:-d}),[rows,sortKey,sortDir]);
 function sort(key:SortKey){if(sortKey===key)setSortDir(d=>d==="desc"?"asc":"desc");else{setSortKey(key);setSortDir(key==="symbol"?"asc":"desc")}}
 function changeWeight(key:string,value:number){if(!Number.isFinite(value)||value<=0)return;setCriteria(c=>({...c,[key]:value}))}
 function remove(key:string){if(activeKeys.length<=1)return;const next={...criteria};delete next[key];setCriteria(next)}
 function add(){if(!addKey)return;setCriteria(c=>({...c,[addKey]:10}));setAddKey("")}
 function usePreset(p:any){const next={...(p.criteria||DEFAULT)};setCriteria(next);setExpanded(null);run(next)}
 async function save(){const name=saveName.trim();if(!name)return;setError("");try{await api("/api/v1/opportunities/formulas",{method:"POST",body:JSON.stringify({name,criteria})});setSaveName("");await loadPresets()}catch(e:any){setError(e?.message||String(e))}}
 async function del(p:any){if(p.built_in)return;setError("");try{await api(`/api/v1/opportunities/formulas/${p.id}`,{method:"DELETE"});await loadPresets()}catch(e:any){setError(e?.message||String(e))}}

 return <div className="formula-builder-v4">
  <div className="formula-toolbar">
   <div><span className="label">Active Opportunity formula</span><h2>{meta?.formula?.label||"Custom Opportunity Index"}</h2><p className="muted">Weights are normalized automatically. Index scores rank relative setup quality; they are not return probabilities.</p></div>
   <div className="formula-actions"><select aria-label="Add Opportunity criterion" value={addKey} onChange={e=>setAddKey(e.target.value)}><option value="">Add Criteria…</option>{available.map(c=><option key={c.key} value={c.key}>{c.label}</option>)}</select><button onClick={add} disabled={!addKey}>Add</button><button onClick={()=>run()} disabled={loading}>{loading?"Searching…":"Search"}</button></div>
  </div>

  <div className="formula-criteria" aria-label="Active formula criteria">{activeKeys.map(key=><div className="formula-criterion" key={key}><div><b>{labelFor(key)}</b><small>{n(effective[key],1)}% effective</small></div><label>Weight <input aria-label={`${labelFor(key)} weight`} type="number" min="0.1" max="1000" step="0.5" value={criteria[key]} onChange={e=>changeWeight(key,Number(e.target.value))}/></label><button aria-label={`Remove ${labelFor(key)}`} onClick={()=>remove(key)} disabled={activeKeys.length<=1}>×</button></div>)}</div>

  <div className="formula-presets"><div className="preset-list"><span className="label">Saved formulas</span>{presets.map(p=><div className="preset-pill" key={String(p.id)}><button onClick={()=>usePreset(p)}>{p.name}</button>{!p.built_in&&<button className="preset-delete" aria-label={`Delete ${p.name}`} onClick={()=>del(p)}>×</button>}</div>)}</div><div className="save-formula"><input value={saveName} onChange={e=>setSaveName(e.target.value)} placeholder="Formula name" aria-label="Formula name"/><button onClick={save} disabled={!saveName.trim()}>Save Formula</button></div></div>
  {error&&<div className="v4-error"><span>{error}</span></div>}

  <div className="opportunity-index-head"><div><span className="label">Opportunity index</span><h2>Full-universe ranking</h2></div><div className="mini-stats"><span>Eligible <b>{meta?.counts?.formula_complete??"—"}</b></span><span>Returned <b>{rows.length}</b></span><span>Cache <b>{meta?.last_cache_update?new Date(meta.last_cache_update).toLocaleString():"—"}</b></span></div></div>
  <div className="metric-sort-bar formula-sort"><button className={sortKey==="score"?"active":""} onClick={()=>sort("score")}>Index</button><button className={sortKey==="williams"?"active":""} onClick={()=>sort("williams")}>Williams %R</button><button className={sortKey==="ma100_proximity"?"active":""} onClick={()=>sort("ma100_proximity")}>100MA distance</button><button className={sortKey==="ma100_slope"?"active":""} onClick={()=>sort("ma100_slope")}>100MA slope</button><button className={sortKey==="approach_velocity"?"active":""} onClick={()=>sort("approach_velocity")}>Approach</button><button className={sortKey==="liquidity"?"active":""} onClick={()=>sort("liquidity")}>Liquidity</button><button className={sortKey==="symbol"?"active":""} onClick={()=>sort("symbol")}>Ticker</button><span className="muted">{sortDir==="desc"?"↓":"↑"}</span></div>
  {loading&&!rows.length?<p className="muted" role="status">Ranking cached market universe…</p>:<div className="opportunity-index-table">
   <div className="opportunity-index-row header"><b>#</b><b>Ticker</b><span>Index</span><span>W%R</span><span>100MA</span><span>Slope</span><span>Approach</span><span>Liquidity</span></div>
   {sorted.map((r:any)=><div className="opportunity-index-entry" key={r.symbol}><button className="opportunity-index-row" onClick={()=>setExpanded(expanded===r.symbol?null:r.symbol)} aria-expanded={expanded===r.symbol}><b>{r.rank}</b><div><strong>{r.symbol}</strong><small>{r.sector||r.industry||"—"}</small></div><b>{n(r.score,1)}</b><span>{n(r.raw_criteria?.williams,1)}</span><span>{r.raw_criteria?.ma100_proximity==null?"—":`${n(r.raw_criteria.ma100_proximity,1)}%`}</span><span>{r.raw_criteria?.ma100_slope==null?"—":`${n(r.raw_criteria.ma100_slope,2)}%`}</span><span>{n(r.raw_criteria?.approach_velocity,2)}</span><span>{money(r.average_dollar_volume_20d)}</span></button>{expanded===r.symbol&&<div className="opportunity-index-detail"><div className="source-state-grid"><span><i>Price</i><b>{r.price==null?"—":`$${n(r.price,2)}`}</b></span><span><i>1D</i><b>{r.change_percent==null?"—":`${n(r.change_percent,2)}%`}</b></span><span><i>7D</i><b>{r.seven_day_percent==null?"—":`${n(r.seven_day_percent,2)}%`}</b></span><span><i>30D</i><b>{r.thirty_day_percent==null?"—":`${n(r.thirty_day_percent,2)}%`}</b></span><span><i>MA100</i><b>{n(r.ma100,2)}</b></span><span><i>MA200</i><b>{n(r.ma200,2)}</b></span><span><i>Relative volume</i><b>{n(r.relative_volume,2)}</b></span><span><i>Verification</i><b>{String(r.verification_status||"unknown").replaceAll("_"," ")}</b></span></div><div className="criterion-breakdown">{activeKeys.map(key=><span key={key}>{labelFor(key)} <b>{n(r.criterion_scores?.[key],1)}</b> × {n(effective[key],1)}%</span>)}</div><div className="detail-actions"><button onClick={()=>onOpen(r.symbol)}>Open unified research</button>{r.source_url&&<a className="source-link" href={r.source_url} target="_blank" rel="noreferrer">Source ↗</a>}</div></div>}</div>)}
  </div>}
 </div>
}
