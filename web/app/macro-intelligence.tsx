"use client";

type Reason={reason_type?:"news"|"technical";title:string;url?:string;domain?:string;published_at?:string;discovery_source?:string;matched_symbol?:string;matched_group?:string;inference?:string;confidence?:string;match_score?:number;evidence?:string[];move_context?:string};
type Suggestion={symbol:string;name:string;theme:string;why:string};

function ReasonRow({reason}:{reason:Reason}){
 const body=<><div className="reason-head"><div><span className={`reason-type ${reason.reason_type||"news"}`}>{reason.reason_type==="technical"?"Technical":"News catalyst"}</span>{reason.matched_symbol&&<span className="reason-symbol">{reason.matched_symbol}</span>}</div><span className={`confidence ${reason.confidence||"low"}`}>{reason.confidence||"low"}</span></div><strong>{reason.title}</strong><p>{reason.inference}</p>{reason.evidence?.filter(Boolean).length?<div className="reason-evidence">{reason.evidence.filter(Boolean).map(x=><span key={x}>{x}</span>)}</div>:null}<div className="reason-meta">{reason.domain&&<span>{reason.domain}</span>}{reason.discovery_source&&<span>{reason.discovery_source}</span>}{reason.published_at&&<span>{reason.published_at}</span>}{reason.match_score!=null&&<span>match {reason.match_score.toFixed(0)}</span>}</div></>;
 return reason.url?<a className="reason-row" href={reason.url} target="_blank" rel="noreferrer">{body}</a>:<div className="reason-row">{body}</div>;
}

export function MacroReasons({rotation}:{rotation:any}){
 const news:Reason[]=rotation?.possible_reasons||[];
 const technical:Reason[]=rotation?.technical_reasons||[];
 const meta=rotation?.news_context||{};
 return <div className="card reveal-card macro-reasons-card">
  <div className="section-head"><div><span className="eyebrow">Catalyst matching</span><h2>Possible reasons</h2></div><span className="reason-count">{news.length+technical.length} signals</span></div>
  <p className="muted">News matches and technical explanations are evidence candidates, not causal claims. The model now separates external catalysts from price/volume structure.</p>
  <div className="reason-columns">
   <section><div className="reason-section-title"><strong>News / event matches</strong><span>{meta.source_count?`${meta.source_count} source domains`:"multi-source feed"}</span></div>{news.length?news.map((r,i)=><ReasonRow reason={{...r,reason_type:"news"}} key={`${r.url||r.title}-${i}`}/>):<p className="muted empty-reason">No sufficiently strong news match in the current feed.</p>}</section>
   <section><div className="reason-section-title"><strong>Technical explanations</strong><span>trend · volume · momentum · levels</span></div>{technical.length?technical.map((r,i)=><ReasonRow reason={{...r,reason_type:"technical"}} key={`${r.matched_symbol||"technical"}-${r.title}-${i}`}/>):<p className="muted empty-reason">No strong technical explanation was generated from the stored snapshot.</p>}</section>
  </div>
  {rotation?.reasoning_methodology&&<p className="reason-methodology">{rotation.reasoning_methodology}</p>}
 </div>
}

export function EtfSuggestions({items}:{items:Suggestion[]|undefined}){
 if(!items?.length)return null;
 return <div className="card reveal-card etf-suggestion-card"><div className="section-head"><div><span className="eyebrow">Coverage expansion</span><h2>Suggested macro ETFs</h2></div><span className="reason-count">Research list</span></div><p className="muted">Candidates that add information not fully captured by the current broad-sector set. These are tracking suggestions, not investment recommendations.</p><div className="etf-suggestion-grid">{items.map(x=><article key={x.symbol}><div><strong>{x.symbol}</strong><span>{x.theme}</span></div><h3>{x.name}</h3><p>{x.why}</p></article>)}</div></div>
}
