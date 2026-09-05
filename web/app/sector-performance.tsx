"use client";

const pct=(v:number|null|undefined)=>v==null?"—":`${v>=0?"+":""}${v.toFixed(2)}%`;
export default function SectorPerformance({sectors}:{sectors:any[]}){
 const rows=[...(sectors||[])].sort((a,b)=>(b.seven_day_percent??-999)-(a.seven_day_percent??-999));
 const max=Math.max(1,...rows.map(r=>Math.abs(r.seven_day_percent||0)));
 return <div className="card sector-performance-card"><div className="section-head"><div><span className="eyebrow">Relative strength</span><h2>Sector Performance</h2></div><span className="muted small-note">7D</span></div><div className="sector-bars">{rows.map((r:any)=><div className="sector-bar-row" key={r.symbol}><div className="sector-label"><strong>{r.name}</strong><span>{r.symbol}</span></div><div className="sector-track"><div className={`sector-fill ${(r.seven_day_percent||0)>=0?"up":"down"}`} style={{width:`${Math.max(3,Math.abs(r.seven_day_percent||0)/max*100)}%`}}/></div><strong className={(r.seven_day_percent||0)>=0?"positive":"negative"}>{pct(r.seven_day_percent)}</strong></div>)}</div></div>;
}
