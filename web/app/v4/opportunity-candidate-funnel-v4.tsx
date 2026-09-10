"use client";

import {useCallback,useEffect,useMemo,useRef,useState} from "react";
import type {ActiveOpportunityFormula} from "./opportunity-formula-builder-v4";

const API="/backend";
const AUTO_REFRESH_MS=5*60*1000;

async function api(path:string,init?:RequestInit){
 const r=await fetch(`${API}${path}`,{credentials:"include",cache:"no-store",...init,headers:{"content-type":"application/json",...(init?.headers||{})}});
 const d=await r.json().catch(()=>({}));
 if(!r.ok)throw new Error(d?.detail||`HTTP ${r.status}`);
 return d;
}
const n=(v:any,d=1)=>v==null?"—":Number(v).toFixed(d);
const stage=(x:string)=>String(x||"watch").replaceAll("_"," ").replace(/\b\w/g,c=>c.toUpperCase());
const freshness=(x:any)=>!x?.available?"Missing":x?.fresh?"Fresh":"Stale";

export default function OpportunityCandidateFunnelV4({onOpen,formula}:{onOpen:(symbol:string)=>void;formula:ActiveOpportunityFormula|null}){
 const[data,setData]=useState<any>(null),[loading,setLoading]=useState(false),[error,setError]=useState(""),[autoRefresh,setAutoRefresh]=useState(true),[lastBuiltRevision,setLastBuiltRevision]=useState<number|null>(null);
 const formulaRef=useRef(formula);useEffect(()=>{formulaRef.current=formula},[formula]);
 const build=useCallback(async(source:"manual"|"formula"|"timer"|"fundamentals"|"context"="manual",enrich=false,refreshContext=false)=>{const active=formulaRef.current;if(!active)return;setLoading(true);setError("");try{const d=await api(`/api/v1/opportunities/funnel?limit=50&enrich=${enrich?"true":"false"}&refresh_context=${refreshContext?"true":"false"}`,{method:"POST",body:JSON.stringify({criteria:active.criteria,filters:active.filters})});setData({...d,refresh_source:source,formula_name:active.name,formula_dirty:active.dirty});setLastBuiltRevision(active.revision)}catch(e:any){setError(e.message||String(e))}finally{setLoading(false)}},[]);
 useEffect(()=>{if(!formula||formula.revision<=0)return;if(lastBuiltRevision===null){build("formula");return}if(formula.revision!==lastBuiltRevision)build("formula")},[formula?.revision,lastBuiltRevision,build]);
 useEffect(()=>{if(!autoRefresh||!data)return;const id=setInterval(()=>build("timer"),AUTO_REFRESH_MS);return()=>clearInterval(id)},[autoRefresh,Boolean(data),build]);
 const staleFormula=useMemo(()=>Boolean(formula&&data&&(data.formula_name!==formula.name||data.formula_dirty!==formula.dirty||lastBuiltRevision!==formula.revision)),[formula,data,lastBuiltRevision]);
 const recentTransitions=(data?.recent_stage_transitions||[]).slice(0,8);
 const ctx=data?.candidate_context||{};
 const staleContext=Math.max(0,(ctx?.candidate_count||0)-Math.min(ctx?.fresh?.news||0,ctx?.fresh?.flow||0,ctx?.fresh?.catalysts||0));
 return <section className="formula-funnel-v4">
  <div className="formula-funnel-head">
   <div><span className="label">Candidate funnel</span><h2>Active formula → attention shortlist</h2><p className="muted">The funnel uses the formula currently being edited above, including unsaved weights and hard screens. Automatic builds are cache-only; formula rank remains primary and liquidity is eligibility-only.</p></div>
   <div className="formula-funnel-actions"><span className="formula-live-name">{formula?.name||"Loading formula…"}{formula?.dirty?" · Unsaved changes":""}</span><button onClick={()=>build("manual")} disabled={!formula||loading}>{loading?"Building…":"Build Shortlist"}</button><button onClick={()=>build("fundamentals",true,false)} disabled={!formula||loading||!(data?.fundamental_enrichment_targets||[]).length}>Refresh Fundamentals</button><button onClick={()=>build("context",false,true)} disabled={!formula||loading||!data||staleContext===0}>Refresh Top Context</button><button aria-pressed={autoRefresh} className={autoRefresh?"active":""} onClick={()=>setAutoRefresh(x=>!x)}>{autoRefresh?"Auto refresh on":"Auto refresh off"}</button></div>
  </div>
  {staleFormula&&!loading&&<div className="v4-warning"><span>Formula changed since this shortlist was built. Run Search above or Build Shortlist to refresh it.</span></div>}
  {error&&<div className="v4-error"><span>{error}</span></div>}
  {data&&<>
   <div className="funnel-stage-strip">{(data.stages||[]).map((s:any)=><div key={s.name}><span>{s.name}</span><strong>{s.input??"—"} → {s.output??"—"}</strong><small>{s.rule}</small></div>)}</div>
   <div className="mini-stats"><span>Watch <b>{data.attention_counts?.watch??0}</b></span><span>Developing <b>{data.attention_counts?.developing??0}</b></span><span>Actionable <b>{data.attention_counts?.actionable??0}</b></span><span>High conviction <b>{data.attention_counts?.high_conviction??0}</b></span><span>Fund. targets <b>{data.fundamental_enrichment_targets?.length??0}</b></span><span>Updated <b>{data.generated_at?new Date(data.generated_at).toLocaleTimeString():"—"}</b></span></div>
   <div className="mini-stats"><span>Fresh fundamentals <b>{ctx?.fresh?.fundamentals??0}/{ctx?.candidate_count??0}</b></span><span>Fresh news <b>{ctx?.fresh?.news??0}/{ctx?.candidate_count??0}</b></span><span>Fresh catalysts <b>{ctx?.fresh?.catalysts??0}/{ctx?.candidate_count??0}</b></span><span>Fresh flow <b>{ctx?.fresh?.flow??0}/{ctx?.candidate_count??0}</b></span>{(data.fundamental_jobs_added||[]).length>0&&<span>Queued fundamentals <b>{data.fundamental_jobs_added.length}</b></span>}{data.live_context_refresh&&<span>Context refreshed <b>{data.live_context_refresh.refreshed?.length??0}/{data.live_context_refresh.requested?.length??0}</b></span>}</div>
   {data.live_context_refresh?.errors?.length>0&&<div className="v4-warning"><span>{data.live_context_refresh.errors.length} bounded context refresh request(s) failed; cached evidence remains visible.</span></div>}
   {recentTransitions.length>0&&<details className="funnel-transition-log" open><summary><strong>Recent stage changes</strong><span>{data.stage_transitions?.length??0} this refresh</span></summary><div>{recentTransitions.map((t:any,i:number)=><button key={`${t.symbol}-${t.at}-${i}`} onClick={()=>t.symbol&&onOpen(t.symbol)}><b>{t.symbol}</b><span>{stage(t.from)} → {stage(t.to)}</span><small>{t.at?new Date(t.at).toLocaleString():"—"}{t.formula_score!=null?` · formula ${n(t.formula_score)}`:""}</small></button>)}</div></details>}
   <div className="funnel-candidate-list">{(data.candidates||[]).map((c:any)=>{const cc=c.candidate_context||{},sections=cc.sections||{};return <details key={c.symbol} className={`funnel-candidate attention-${c.attention_stage||"watch"}`}><summary><b>#{c.priority_rank} {c.symbol}</b><span>{stage(c.attention_stage)}</span><span>Formula #{c.formula_rank} · {n(c.formula_score)}</span><span>Priority {n(c.contextual_priority_score)}</span><span>{stage(c.convergence?.state)}</span></summary><div className="funnel-candidate-detail"><div className="source-state-grid"><span><i>Williams</i><b>{n(c.williams_r_14,2)}</b></span><span><i>100MA distance</i><b>{c.price_vs_ma100_percent==null?"—":`${n(c.price_vs_ma100_percent,2)}%`}</b></span><span><i>Rotation</i><b>{stage(c.rotation_state)}</b></span><span><i>Feature context</i><b>{stage(c.feature_context_status)}</b></span><span><i>Fundamentals</i><b>{freshness(sections.fundamentals)}</b></span><span><i>News</i><b>{freshness(sections.news)} · {cc.news?.count??0}</b></span><span><i>Catalysts</i><b>{freshness(sections.catalysts)} · {cc.catalysts?.count??0}</b></span><span><i>Flow</i><b>{freshness(sections.flow)} · {cc.flow?.count??0}</b></span><span><i>Verification</i><b>{stage(c.verification_status)}</b></span></div>{(cc.catalysts?.upcoming||[]).length>0&&<div className="funnel-context-block"><b>Upcoming catalysts</b>{cc.catalysts.upcoming.map((x:any,i:number)=><span key={i}>{x.date||"—"} · {x.title||x.kind||"Catalyst"} · {x.impact||"unrated"}</span>)}</div>}{(cc.news?.top||[]).length>0&&<div className="funnel-context-block"><b>Linked news</b>{cc.news.top.map((x:any,i:number)=><span key={i}>{x.title||"Untitled"}</span>)}</div>}{(cc.flow?.top||[]).length>0&&<div className="funnel-context-block"><b>Recent flow</b>{cc.flow.top.map((x:any,i:number)=><span key={i}>{x.label||x.description||x.symbol||"Flow observation"}</span>)}</div>}<div className="funnel-explain">{Object.values(c.explain||{}).map((v:any,i)=><p key={i}>{String(v)}</p>)}</div><button onClick={()=>onOpen(c.symbol)}>Open unified research</button></div></details>})}</div>
  </>}
  {!data&&!loading&&<p className="muted">The shortlist will build automatically after the active formula completes its first market-wide Search, or you can build it manually.</p>}
 </section>
}
