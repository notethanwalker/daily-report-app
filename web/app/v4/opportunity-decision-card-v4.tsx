"use client";

const words=(v:any)=>String(v||"—").replaceAll("_"," ").replace(/\b\w/g,c=>c.toUpperCase());
const n=(v:any,d=1)=>v==null?"—":Number(v).toFixed(d);

function EvidenceList({title,items}:{title:string;items:any[]}){
 const rows=Array.isArray(items)?items:[];
 return <div className="decision-evidence-column"><h4>{title}</h4>{rows.length?rows.map((x:any,i:number)=><p key={i}>{String(x)}</p>):<p className="muted">No current evidence.</p>}</div>;
}

export default function OpportunityDecisionCardV4({card}:{card:any}){
 if(!card)return null;
 const q=card.data_quality||{},flow=card.flow_confirmation||{},asset=card.asset_opportunity||{},fit=card.portfolio_fit||{};
 return <section className="opportunity-decision-card-v4">
  <div className="section-head"><div><span className="label">Decision card</span><h3>Transparent setup synthesis</h3></div><span>{words(card.attention_stage)}</span></div>
  <div className="source-state-grid">
   <span><i>Asset Opportunity</i><b>#{asset.rank??"—"} · {n(asset.score)}</b></span>
   <span><i>Portfolio Fit</i><b>#{fit.rank??"—"} · {n(fit.score)} · {words(fit.confidence)}</b></span>
   <span><i>Data quality</i><b>{words(q.label)}</b></span>
   <span><i>Context coverage</i><b>{q.context_completeness==null?"—":`${n(Number(q.context_completeness)*100,0)}%`}</b></span>
   <span><i>Context freshness</i><b>{q.context_freshness==null?"—":`${n(Number(q.context_freshness)*100,0)}%`}</b></span>
   <span><i>Verification</i><b>{words(q.verification)}</b></span>
   <span><i>Persistent flow</i><b>{words(flow.verdict)} · {words(flow.confidence)}</b></span>
   <span><i>Flow score effect</i><b>{flow.score_effect??0}</b></span>
  </div>
  <div className="decision-evidence-grid">
   <EvidenceList title="Bull case" items={card.bull_case}/>
   <EvidenceList title="Bear case" items={card.bear_case}/>
   <EvidenceList title="Current blockers" items={card.blockers}/>
   <EvidenceList title="Invalidation" items={card.invalidation}/>
   <EvidenceList title="Upgrade triggers" items={card.upgrade_triggers}/>
   <EvidenceList title="Downgrade triggers" items={card.downgrade_triggers}/>
  </div>
  <p className="muted">{card.policy}</p>
 </section>;
}
