"use client";

type Rate={pair:string;rate:number|null;seven_day_percent:number|null};
type CurrencyData={base?:string;as_of?:string;comparison_date?:string;provider?:string;source_url?:string;rates?:Rate[]};
const pct=(v:number|null|undefined)=>v==null?"—":`${v>=0?"+":""}${v.toFixed(2)}%`;

export default function CurrencyPanel({data,title="World Currencies"}:{data:CurrencyData|null|undefined;title?:string}){
 const rows=data?.rates||[];
 return <div className="card reveal-card currency-card">
  <div className="section-head"><div><span className="eyebrow">FX context</span><h2>{title}</h2></div>{data?.source_url&&<a className="source-link compact-source" href={data.source_url} target="_blank" rel="noreferrer">{data.provider||"Source"} ↗</a>}</div>
  {rows.length?<><div className="currency-grid">{rows.map(r=><div className="currency-row" key={r.pair}><div><strong>{r.pair}</strong><span>USD base</span></div><strong>{r.rate==null?"—":r.rate.toLocaleString(undefined,{maximumFractionDigits:4})}</strong><span className={(r.seven_day_percent??0)>=0?"positive":"negative"}>{pct(r.seven_day_percent)}</span></div>)}</div><p className="muted currency-note">As of {data?.as_of||"latest"}; 7-day comparison {data?.comparison_date||"latest available session"}.</p></>:<p className="muted">Currency data is not currently available.</p>}
 </div>
}
