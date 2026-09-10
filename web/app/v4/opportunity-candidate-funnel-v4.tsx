"use client";

import {useEffect,useMemo,useState} from "react";

const API="/backend";

type Preset={id:string|number;name:string;built_in?:boolean;criteria:Record<string,number>;filters?:Array<{field:string;operator:string;value:number}>};

async function api(path:string,init?:RequestInit){
 const r=await fetch(`${API}${path}`,{credentials:"include",cache:"no-store",...init,headers:{"content-type":"application/json",...(init?.headers||{})}});
 const d=await r.json().catch(()=>({}));
 if(!r.ok)throw new Error(d?.detail||`HTTP ${r.status}`);
 return d;
}
const n=(v:any,d=1)=>v==null?"—":Number(v).toFixed(d);
const stage=(x:string)=>String(x||"watch").replaceAll("_"," ").replace(/\b\w/g,c=>c.toUpperCase());

export default function OpportunityCandidateFunnelV4({onOpen}:{onOpen:(symbol:string)=>void}){
 const[presets,setPresets]=useState<Preset[]>([]),[presetId,setPresetId]=useState<string>("default"),[data,setData]=useState<any>(null),[loading,setLoading]=useState(false),[error,setError]=useState("");
 useEffect(()=>{api("/api/v1/opportunities/formulas").then(d=>setPresets([d.default,...(d.saved||[])])).catch(e=>setError(e.message||String(e)))},[]);
 const preset=useMemo(()=>presets.find(p=>String(p.id)===presetId)||presets[0],[presets,presetId]);
 async function build(){if(!preset)return;setLoading(true);setError("");try{setData(await api("/api/v1/opportunities/funnel?limit=50",{method:"POST",body:JSON.stringify({criteria:preset.criteria,filters:preset.filters||[]})}))}catch(e:any){setError(e.message||String(e))}finally{setLoading(false)}}
 return <section className="formula-funnel-v4">
  <div className="formula-funnel-head">
   <div><span className="label">Candidate funnel</span><h2>Formula → attention shortlist</h2><p className="muted">Use a saved formula to reduce the market-wide index into a bounded shortlist. Context can refine priority, but formula rank remains visible and liquidity never adds bonus points.</p></div>
   <div className="formula-funnel-actions"><select value={presetId} onChange={e=>setPresetId(e.target.value)} aria-label="Candidate funnel formula">{presets.map(p=><option key={String(p.id)} value={String(p.id)}>{p.name}</option>)}</select><button onClick={build} disabled={!preset||loading}>{loading?"Building…":"Build Shortlist"}</button></div>
  </div>
  {error&&<div className="v4-error"><span>{error}</span></div>}
  {data&&<>
   <div className="funnel-stage-strip">{(data.stages||[]).map((s:any)=><div key={s.name}><span>{s.name}</span><strong>{s.input??"—"} → {s.output??"—"}</strong><small>{s.rule}</small></div>)}</div>
   <div className="mini-stats"><span>Watch <b>{data.attention_counts?.watch??0}</b></span><span>Developing <b>{data.attention_counts?.developing??0}</b></span><span>Actionable <b>{data.attention_counts?.actionable??0}</b></span><span>High conviction <b>{data.attention_counts?.high_conviction??0}</b></span><span>Deep enrichment <b>{data.deep_enrichment_symbols?.length??0}</b></span></div>
   <div className="funnel-candidate-list">{(data.candidates||[]).map((c:any)=><details key={c.symbol} className={`funnel-candidate attention-${c.attention_stage||"watch"}`}><summary><b>#{c.priority_rank} {c.symbol}</b><span>{stage(c.attention_stage)}</span><span>Formula #{c.formula_rank} · {n(c.formula_score)}</span><span>Priority {n(c.contextual_priority_score)}</span><span>{stage(c.convergence?.state)}</span></summary><div className="funnel-candidate-detail"><div className="source-state-grid"><span><i>Williams</i><b>{n(c.williams_r_14,2)}</b></span><span><i>100MA distance</i><b>{c.price_vs_ma100_percent==null?"—":`${n(c.price_vs_ma100_percent,2)}%`}</b></span><span><i>Rotation</i><b>{stage(c.rotation_state)}</b></span><span><i>Rotation conviction</i><b>{n(c.rotation_conviction)}%</b></span><span><i>Enrichment</i><b>{stage(c.enrichment_status)}</b></span><span><i>Verification</i><b>{stage(c.verification_status)}</b></span></div><div className="funnel-explain">{Object.values(c.explain||{}).map((v:any,i)=><p key={i}>{String(v)}</p>)}</div><button onClick={()=>onOpen(c.symbol)}>Open unified research</button></div></details>)}</div>
  </>}
  {!data&&!loading&&<p className="muted">Save a custom formula in the builder above, then select it here to generate a candidate shortlist.</p>}
 </section>
}
