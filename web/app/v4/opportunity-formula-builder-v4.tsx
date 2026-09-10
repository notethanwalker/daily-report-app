"use client";

import {useEffect,useMemo,useState} from "react";

const API="/backend";
const DEFAULT={williams:60,ma100_proximity:30,ma100_slope:5,approach_velocity:5};
type CriteriaMap=Record<string,number>;
type HardFilter={field:string;operator:string;value:number};
type SortKey="score"|"williams"|"ma100_proximity"|"ma50_proximity"|"ma100_slope"|"approach_velocity"|"relative_volume"|"liquidity"|"symbol";
type SortDir="asc"|"desc";

async function api(path:string,init?:RequestInit){
 const r=await fetch(`${API}${path}`,{credentials:"include",cache:"no-store",...init,headers:{"content-type":"application/json",...(init?.headers||{})}});
 const d=await r.json().catch(()=>({}));
 if(!r.ok)throw new Error(d?.detail||`HTTP ${r.status}`);
 return d;
}
const n=(v:any,d=1)=>v==null?"—":Number(v).toFixed(d);
const money=(v:any)=>v==null?"—":Number(v)>=1e9?`$${(Number(v)/1e9).toFixed(1)}B`:Number(v)>=1e6?`$${(Number(v)/1e6).toFixed(1)}M`:`$${Number(v).toLocaleString()}`;
function opportunityTone(x:any){
 const score=Number(x.score??50),wr=Number(x.raw_criteria?.williams??0),ma=Number(x.raw_criteria?.ma100_proximity??0);
 if(score>=80||((wr<=-80)&&(ma>=0&&ma<=5)))return "strength-strong";
 if(score>=68||wr<=-70)return "strength-positive";
 if(score<=38)return "strength-weak";
 if(score<=50)return "strength-negative";
 return "strength-neutral";
}

export default function OpportunityFormulaBuilderV4({onOpen}:{onOpen:(symbol:string)=>void}){
 const[catalog,setCatalog]=useState<any[]>([]),[filterCatalog,setFilterCatalog]=useState<any[]>([]),[criteria,setCriteria]=useState<CriteriaMap>(DEFAULT),[filters,setFilters]=useState<HardFilter[]>([]),[rows,setRows]=useState<any[]>([]),[meta,setMeta]=useState<any>(null),[presets,setPresets]=useState<any[]>([]);
 const[loading,setLoading]=useState(true),[error,setError]=useState(""),[addKey,setAddKey]=useState(""),[addFilterKey,setAddFilterKey]=useState(""),[saveName,setSaveName]=useState(""),[expanded,setExpanded]=useState<string|null>(null),[activePresetId,setActivePresetId]=useState<string|number|null>("default"),[dirty,setDirty]=useState(false);
 const[sortKey,setSortKey]=useState<SortKey>("score"),[sortDir,setSortDir]=useState<SortDir>("desc");

 async function loadPresets(){const d=await api("/api/v1/opportunities/formulas");setPresets([d.default,...(d.saved||[])]);return d;}
 async function run(next:CriteriaMap=criteria,nextFilters:HardFilter[]=filters,nextSort:SortKey=sortKey,nextDir:SortDir=sortDir){
  setLoading(true);setError("");
  try{
   const q=new URLSearchParams({limit:"500",sort_by:nextSort,sort_dir:nextDir});
   const d=await api(`/api/v1/opportunities/index?${q.toString()}`,{method:"POST",body:JSON.stringify({criteria:next,filters:nextFilters})});
   setRows(d.rows||[]);setMeta(d);
  }catch(e:any){setError(e?.message||String(e))}finally{setLoading(false)}
 }
 useEffect(()=>{(async()=>{try{const[c,p]=await Promise.all([api("/api/v1/opportunities/criteria"),api("/api/v1/opportunities/formulas")]);setCatalog(c.criteria||[]);setFilterCatalog(c.filters||[]);setPresets([p.default,...(p.saved||[])]);setCriteria(c.default_formula?.criteria||DEFAULT);setFilters(c.default_formula?.filters||[]);await run(c.default_formula?.criteria||DEFAULT,c.default_formula?.filters||[],"score","desc")}catch(e:any){setError(e?.message||String(e));setLoading(false)}})()},[]);

 const activeKeys=Object.keys(criteria);
 const available=catalog.filter(c=>!activeKeys.includes(c.key));
 const effective=useMemo(()=>{const total=Object.values(criteria).reduce((a,b)=>a+Number(b||0),0);return Object.fromEntries(Object.entries(criteria).map(([k,v])=>[k,total?Number(v)/total*100:0]))},[criteria]);
 const labelFor=(key:string)=>catalog.find(c=>c.key===key)?.label||key;
 const infoFor=(key:string)=>catalog.find(c=>c.key===key)||{};
 const filterInfo=(field:string)=>filterCatalog.find(c=>c.key===field)||{label:field,operators:["<=",">="]};
 const activePreset=presets.find(p=>String(p.id)===String(activePresetId));
 function markDirty(){setDirty(true)}
 function sort(key:SortKey){const nextDir:SortDir=sortKey===key?(sortDir==="desc"?"asc":"desc"):(key==="symbol"?"asc":"desc");setSortKey(key);setSortDir(nextDir);setExpanded(null);run(criteria,filters,key,nextDir)}
 function changeWeight(key:string,value:number){if(!Number.isFinite(value)||value<=0)return;markDirty();setCriteria(c=>({...c,[key]:value}))}
 function remove(key:string){if(activeKeys.length<=1)return;markDirty();const next={...criteria};delete next[key];setCriteria(next)}
 function add(){if(!addKey)return;markDirty();setCriteria(c=>({...c,[addKey]:10}));setAddKey("")}
 function addFilter(){const info=filterInfo(addFilterKey);if(!addFilterKey||!info)return;markDirty();setFilters(xs=>[...xs,{field:addFilterKey,operator:info.default_operator||info.operators?.[0]||"<=",value:Number(info.default_value??0)}]);setAddFilterKey("")}
 function updateFilter(i:number,patch:Partial<HardFilter>){markDirty();setFilters(xs=>xs.map((x,j)=>j===i?{...x,...patch}:x))}
 function removeFilter(i:number){markDirty();setFilters(xs=>xs.filter((_,j)=>j!==i))}
 function usePreset(p:any){const next={...(p.criteria||DEFAULT)},nextFilters=[...(p.filters||[])];setActivePresetId(p.id);setSaveName(p.built_in?"":p.name);setDirty(false);setCriteria(next);setFilters(nextFilters);setExpanded(null);run(next,nextFilters,sortKey,sortDir)}
 async function save(){const name=saveName.trim();if(!name)return;setError("");try{const created=await api("/api/v1/opportunities/formulas",{method:"POST",body:JSON.stringify({name,criteria,filters})});setActivePresetId(created.id);setSaveName(created.name);setDirty(false);await loadPresets()}catch(e:any){setError(e?.message||String(e))}}
 async function updatePreset(){if(!activePreset||activePreset.built_in)return;const name=saveName.trim()||activePreset.name;setError("");try{const updated=await api(`/api/v1/opportunities/formulas/${activePreset.id}`,{method:"PUT",body:JSON.stringify({name,criteria,filters})});setSaveName(updated.name);setActivePresetId(updated.id);setDirty(false);await loadPresets()}catch(e:any){setError(e?.message||String(e))}}
 async function duplicatePreset(){const base=(saveName.trim()||activePreset?.name||"Opportunity Formula").replace(/\s+Copy$/i,"");setError("");try{const created=await api("/api/v1/opportunities/formulas",{method:"POST",body:JSON.stringify({name:`${base} Copy`,criteria,filters})});setSaveName(created.name);setActivePresetId(created.id);setDirty(false);await loadPresets()}catch(e:any){setError(e?.message||String(e))}}
 async function del(p:any){if(p.built_in)return;setError("");try{await api(`/api/v1/opportunities/formulas/${p.id}`,{method:"DELETE"});if(String(activePresetId)===String(p.id)){setActivePresetId("default");setSaveName("");setDirty(false)}await loadPresets()}catch(e:any){setError(e?.message||String(e))}}

 return <div className="formula-builder-v4">
  <div className="formula-toolbar">
   <div><span className="label">Active Opportunity formula</span><h2>{activePreset?.name||"Custom Opportunity Formula"}{dirty?" · Modified":""}</h2><p className="muted">{meta?.formula?.label||"Weights are normalized automatically."} Index scores rank relative setup quality; they are not return probabilities.</p></div>
   <div className="formula-actions"><select aria-label="Add Opportunity criterion" value={addKey} onChange={e=>setAddKey(e.target.value)}><option value="">Add Criteria…</option>{available.map(c=><option key={c.key} value={c.key}>{c.label} · {c.min_sessions||"?"} sessions</option>)}</select><button onClick={add} disabled={!addKey}>Add</button><button onClick={()=>run()} disabled={loading}>{loading?"Searching…":"Search"}</button></div>
  </div>
  <div className="formula-criteria" aria-label="Active formula criteria">{activeKeys.map(key=>{const info=infoFor(key);return <div className="formula-criterion" key={key}><div><b>{labelFor(key)}</b><small>{n(effective[key],1)}% effective · min {info.min_sessions||"?"} sessions</small></div><label>Weight <input aria-label={`${labelFor(key)} weight`} type="number" min="0.1" max="1000" step="0.5" value={criteria[key]} onChange={e=>changeWeight(key,Number(e.target.value))}/></label><button aria-label={`Remove ${labelFor(key)}`} onClick={()=>remove(key)} disabled={activeKeys.length<=1}>×</button><details className="criterion-info"><summary>Why this factor?</summary><p>{info.description||"No description available."}</p><p><b>Hypothesis:</b> {info.hypothesis||"Not documented."}</p></details></div>})}</div>
  <div className="formula-filters"><div className="filter-heading"><div><span className="label">Hard screens</span><p className="muted">Optional requirements applied before ranking. They add no points to the index.</p></div><div className="filter-add"><select aria-label="Add hard screen" value={addFilterKey} onChange={e=>setAddFilterKey(e.target.value)}><option value="">Add Filter…</option>{filterCatalog.map(f=><option key={f.key} value={f.key}>{f.label}</option>)}</select><button onClick={addFilter} disabled={!addFilterKey}>Add</button></div></div>{filters.length>0&&<div className="filter-list">{filters.map((f,i)=>{const info=filterInfo(f.field);return <div className="filter-rule" key={`${f.field}-${i}`}><b>{info.label}</b><select aria-label={`${info.label} operator`} value={f.operator} onChange={e=>updateFilter(i,{operator:e.target.value})}>{(info.operators||[]).map((op:string)=><option key={op} value={op}>{op}</option>)}</select><input aria-label={`${info.label} threshold`} type="number" step="0.1" value={f.value} onChange={e=>updateFilter(i,{value:Number(e.target.value)})}/><button aria-label={`Remove ${info.label} filter`} onClick={()=>removeFilter(i)}>×</button></div>})}</div>}</div>
  <div className="formula-presets"><div className="preset-list"><span className="label">Saved formulas</span>{presets.map(p=><div className={`preset-pill ${String(activePresetId)===String(p.id)?"active":""}`} key={String(p.id)}><button onClick={()=>usePreset(p)}>{p.name}</button>{!p.built_in&&<button className="preset-delete" aria-label={`Delete ${p.name}`} onClick={()=>del(p)}>×</button>}</div>)}</div><div className="save-formula"><input value={saveName} onChange={e=>{setSaveName(e.target.value);if(activePreset&&!activePreset.built_in)setDirty(true)}} placeholder="Formula name" aria-label="Formula name"/><button onClick={save} disabled={!saveName.trim()}>Save New</button>{activePreset&&!activePreset.built_in&&<button onClick={updatePreset} disabled={!dirty}>Update</button>}<button onClick={duplicatePreset}>Duplicate</button></div></div>
  {error&&<div className="v4-error"><span>{error}</span></div>}
  <div className="opportunity-index-head"><div><span className="label">Opportunity index</span><h2>Full-universe ranking</h2></div><div className="mini-stats"><span>Eligible <b>{meta?.counts?.formula_complete??"—"}</b></span><span>Filtered <b>{meta?.counts?.filtered_out??0}</b></span><span>Returned <b>{rows.length}</b></span><span>History <b>{meta?.formula?.required_sessions??"—"} sessions</b></span><span>Cache <b>{meta?.last_cache_update?new Date(meta.last_cache_update).toLocaleString():"—"}</b></span></div></div>
  <div className="metric-sort-bar formula-sort" role="group" aria-label="Click a metric to sort opportunity index"><button aria-pressed={sortKey==="score"} className={sortKey==="score"?"active":""} onClick={()=>sort("score")}>Index</button><button aria-pressed={sortKey==="williams"} className={sortKey==="williams"?"active":""} onClick={()=>sort("williams")}>Williams %R</button><button aria-pressed={sortKey==="ma100_proximity"} className={sortKey==="ma100_proximity"?"active":""} onClick={()=>sort("ma100_proximity")}>100MA distance</button><button aria-pressed={sortKey==="ma50_proximity"} className={sortKey==="ma50_proximity"?"active":""} onClick={()=>sort("ma50_proximity")}>50MA distance</button><button aria-pressed={sortKey==="ma100_slope"} className={sortKey==="ma100_slope"?"active":""} onClick={()=>sort("ma100_slope")}>100MA slope</button><button aria-pressed={sortKey==="approach_velocity"} className={sortKey==="approach_velocity"?"active":""} onClick={()=>sort("approach_velocity")}>Approach</button><button aria-pressed={sortKey==="relative_volume"} className={sortKey==="relative_volume"?"active":""} onClick={()=>sort("relative_volume")}>Rel volume</button><button aria-pressed={sortKey==="liquidity"} className={sortKey==="liquidity"?"active":""} onClick={()=>sort("liquidity")}>Liquidity</button><button aria-pressed={sortKey==="symbol"} className={sortKey==="symbol"?"active":""} onClick={()=>sort("symbol")}>Ticker</button><span className="muted">{sortDir==="desc"?"↓":"↑"}</span></div>
  {loading&&!rows.length?<p className="muted" role="status">Ranking cached market universe…</p>:<div className="opportunity-index-table">
   <div className="opportunity-index-row header"><b>Formula rank</b><b>Ticker</b><span>Index</span><span>W%R</span><span>100MA</span><span>Slope</span><span>Approach</span><span>Liquidity</span></div>
   {rows.map((r:any)=><div className={`opportunity-index-entry ${opportunityTone(r)}`} key={r.symbol}><button className="opportunity-index-row table-row-button" onClick={()=>setExpanded(expanded===r.symbol?null:r.symbol)} aria-expanded={expanded===r.symbol} title={`Open ${r.symbol} details`}><b>{r.formula_rank}</b><div><strong>{r.symbol}</strong><small>{r.sector||r.industry||"—"}</small></div><b>{n(r.score,1)}</b><span>{n(r.raw_criteria?.williams,1)}</span><span>{r.raw_criteria?.ma100_proximity==null?"—":`${n(r.raw_criteria.ma100_proximity,1)}%`}</span><span>{r.raw_criteria?.ma100_slope==null?"—":`${n(r.raw_criteria.ma100_slope,2)}%`}</span><span>{n(r.raw_criteria?.approach_velocity,2)}</span><span>{money(r.average_dollar_volume_20d)}</span></button>{expanded===r.symbol&&<div className="opportunity-index-detail"><div className="source-state-grid"><span><i>Current sort position</i><b>{r.display_position}</b></span><span><i>Price</i><b>{r.price==null?"—":`$${n(r.price,2)}`}</b></span><span><i>1D</i><b>{r.change_percent==null?"—":`${n(r.change_percent,2)}%`}</b></span><span><i>7D</i><b>{r.seven_day_percent==null?"—":`${n(r.seven_day_percent,2)}%`}</b></span><span><i>30D</i><b>{r.thirty_day_percent==null?"—":`${n(r.thirty_day_percent,2)}%`}</b></span><span><i>MA50</i><b>{n(r.ma50,2)}</b></span><span><i>MA100</i><b>{n(r.ma100,2)}</b></span><span><i>MA200</i><b>{n(r.ma200,2)}</b></span><span><i>Relative volume</i><b>{n(r.relative_volume,2)}x</b></span><span><i>Verification</i><b>{String(r.verification_status||"unknown").replaceAll("_"," ")}</b></span></div><div className="criterion-breakdown">{activeKeys.map(key=><span key={key}>{labelFor(key)} <b>{n(r.criterion_scores?.[key],1)}</b> × {n(effective[key],1)}%</span>)}</div><div className="detail-actions"><button onClick={()=>onOpen(r.symbol)} title={`Open ${r.symbol} research`}>Open unified research</button>{r.source_url&&<a className="source-link" href={r.source_url} target="_blank" rel="noreferrer">Source ↗</a>}</div></div>}</div>)}
  </div>}
 </div>
}
