"use client";
import SentimentMeters from "./sentiment-meters";

type Market={symbol:string;price:number|null;change_percent:number|null;seven_day_percent:number|null;thirty_day_percent:number|null;relative_volume:number|null};
type Rotation={leaders:any[];laggards:any[];sectors:any[]};
const money=(v:number|null|undefined)=>v==null?"—":`$${v.toFixed(2)}`;
const pct=(v:number|null|undefined)=>v==null?"—":`${v>=0?"+":""}${v.toFixed(2)}%`;

export default function HomeDashboard({market,rotation,onOpenMarkets,onOpenMacro}:{market:Record<string,Market>;rotation:Rotation|null;onOpenMarkets:()=>void;onOpenMacro:()=>void}){
 const preferred=["SPY","QQQ","SMH","GLD","VIX","IONQ","OKLO"];
 const rows=preferred.map(s=>market[s]).filter(Boolean) as Market[];
 const equityRows=rows.filter(x=>x.symbol!=="VIX"&&x.change_percent!=null);
 const adv=equityRows.filter(x=>(x.change_percent||0)>0).length;
 const breadth=equityRows.length?adv/equityRows.length:0.5;
 const spy=market.SPY?.change_percent||0, qqq=market.QQQ?.change_percent||0, vix=market.VIX?.change_percent||0;
 const score=Math.max(0,Math.min(100,Math.round(50+(breadth-.5)*40+Math.max(-10,Math.min(10,spy*3))+Math.max(-10,Math.min(10,qqq*2))-Math.max(-12,Math.min(12,vix*1.2)))));
 const mood=score>=70?"Greed":score>=58?"Risk-on":score>=42?"Neutral":score>=30?"Risk-off":"Fear";
 const themes=(rotation?.leaders||[]).slice(0,4);
 return <>
  <div className="card home-dashboard-card reveal-card"><div className="section-head"><div><span className="eyebrow">Live overview</span><h2>Market Dashboard</h2></div><button className="text-btn" onClick={onOpenMarkets}>All markets →</button></div>
   <div className="dashboard-table"><div className="dashboard-row dashboard-head"><span>Ticker</span><span>Price</span><span>Day</span><span>7D</span></div>{rows.map(r=><div className="dashboard-row" key={r.symbol}><strong>{r.symbol}</strong><span>{money(r.price)}</span><span className={(r.change_percent||0)>=0?"positive":"negative"}>{pct(r.change_percent)}</span><span className={(r.seven_day_percent||0)>=0?"positive":"negative"}>{pct(r.seven_day_percent)}</span></div>)}</div>
  </div>
  <div className="sentiment-cluster">
   <div className="card sentiment-card reveal-card"><div className="section-head"><div><span className="eyebrow">App composite</span><h2>Market Sentiment</h2></div><strong className="sentiment-label">{mood}</strong></div><div className="sentiment-body"><div className="sentiment-ring" style={{"--score":`${score*3.6}deg`} as React.CSSProperties}><div><strong>{score}</strong><span>/100</span></div></div><div className="sentiment-factors"><div><span>Breadth</span><strong>{equityRows.length?`${adv}/${equityRows.length} up`:"—"}</strong></div><div><span>SPY</span><strong className={spy>=0?"positive":"negative"}>{pct(spy)}</strong></div><div><span>QQQ</span><strong className={qqq>=0?"positive":"negative"}>{pct(qqq)}</strong></div><div><span>VIX</span><strong className={vix<=0?"positive":"negative"}>{pct(vix)}</strong></div></div></div><p className="muted small-note">App-derived score from market breadth, SPY/QQQ direction and VIX change. It is not an external sentiment index.</p></div>
   <SentimentMeters/>
  </div>
  <div className="card themes-card reveal-card"><div className="section-head"><div><span className="eyebrow">Leadership</span><h2>Top Themes</h2></div><button className="text-btn" onClick={onOpenMacro}>Macro →</button></div><div className="theme-list">{themes.length?themes.map((t:any)=><div className="theme-row" key={t.symbol}><div><strong>{t.name}</strong><span>{t.symbol}</span></div><strong className={(t.rotation_score||0)>=0?"positive":"negative"}>{t.rotation_score>=0?"+":""}{t.rotation_score?.toFixed(2)}</strong></div>):<p className="muted">Rotation data has not loaded yet.</p>}</div></div>
 </>;
}
