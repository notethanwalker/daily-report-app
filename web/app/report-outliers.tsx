"use client";
import {useMemo,useState} from "react";
import styles from "./report-additions.module.css";

type Outlier={symbol:string;score?:number|null;reason?:string;change_percent?:number|null;seven_day_percent?:number|null;thirty_day_percent?:number|null;relative_volume?:number|null};
type SortKey="1d"|"7d"|"30d";
const pct=(v:number|null|undefined)=>v==null?"—":`${v>=0?"+":""}${v.toFixed(2)}%`;

export default function ReportOutliers({items}:{items:Outlier[]}){
 const[sort,setSort]=useState<SortKey>("1d");
 const rows=useMemo(()=>[...(items||[])].sort((a,b)=>{const key=sort==="1d"?"change_percent":sort==="7d"?"seven_day_percent":"thirty_day_percent";return Math.abs(Number((b as any)[key]||0))-Math.abs(Number((a as any)[key]||0))}),[items,sort]);
 return <div className="card reveal-card"><div className="section-head"><div><span className="eyebrow">Largest absolute moves</span><h2>Notable Outliers</h2></div><div className={styles.sort}><span className="muted">Sort</span>{(["1d","7d","30d"] as SortKey[]).map(k=><button key={k} className={`toggle ${sort===k?"active":""}`} onClick={()=>setSort(k)}>{k.toUpperCase()}</button>)}</div></div><div className={styles.outlierTable}><div className={styles.outlierHead}><span>Ticker</span><span>1D</span><span>7D</span><span>30D</span><span>Rel Vol</span></div>{rows.map(o=><div className={styles.outlierRow} key={o.symbol}><div><strong>{o.symbol}</strong><small>{o.reason}</small></div><span className={(o.change_percent??0)>=0?"positive":"negative"}>{pct(o.change_percent)}</span><span className={(o.seven_day_percent??0)>=0?"positive":"negative"}>{pct(o.seven_day_percent)}</span><span className={(o.thirty_day_percent??0)>=0?"positive":"negative"}>{pct(o.thirty_day_percent)}</span><span>{o.relative_volume==null?"—":`${o.relative_volume.toFixed(2)}x`}</span></div>)}</div></div>;
}
