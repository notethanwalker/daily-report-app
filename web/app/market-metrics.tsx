"use client";

type Market={symbol:string;price:number|null;change_percent:number|null;seven_day_percent:number|null;thirty_day_percent:number|null;ytd_percent:number|null;ma50?:number|null;ma100:number|null;ma200:number|null;price_vs_ma50_percent?:number|null;price_vs_ma100_percent?:number|null;price_vs_ma200_percent?:number|null;all_time_high?:number|null;price_vs_ath_percent?:number|null;relative_volume:number|null;pe_ratio?:number|null;peg_ratio?:number|null;price_to_sales_ratio?:number|null};
const money=(v:number|null|undefined)=>v==null?"—":`$${v.toFixed(2)}`;
const pct=(v:number|null|undefined)=>v==null?"—":`${v>=0?"+":""}${v.toFixed(2)}%`;
const ratio=(v:number|null|undefined)=>v==null?"—":v.toFixed(2);
const cls=(v:number|null|undefined,invert=false)=>v==null?"":((invert?v<=0:v>=0)?"positive":"negative");
export function MarketGrid({tickers,market,loading,onRefresh}:{tickers:string[];market:Record<string,Market>;loading:Record<string,boolean>;onRefresh:(s:string)=>void}){
 return <div className="card comparison-wrap"><table className="comparison-table"><thead><tr><th>Ticker</th><th>Price</th><th>Day</th><th>7D</th><th>30D</th><th>YTD</th><th>50MA</th><th>100MA</th><th>200MA</th><th>ATH</th><th>vs ATH</th><th>P/S</th><th>P/E</th><th>PEG</th><th>Rel Vol</th><th></th></tr></thead><tbody>{tickers.map(s=>{const d=market[s];return <tr key={s}><td><strong>{s}</strong></td><td>{d?money(d.price):"—"}</td><td className={cls(d?.change_percent)}>{d?pct(d.change_percent):"—"}</td><td className={cls(d?.seven_day_percent)}>{d?pct(d.seven_day_percent):"—"}</td><td className={cls(d?.thirty_day_percent)}>{d?pct(d.thirty_day_percent):"—"}</td><td className={cls(d?.ytd_percent)}>{d?pct(d.ytd_percent):"—"}</td><td className={cls(d?.price_vs_ma50_percent)}>{d?money(d.ma50):"—"}</td><td className={cls(d?.price_vs_ma100_percent)}>{d?money(d.ma100):"—"}</td><td className={cls(d?.price_vs_ma200_percent)}>{d?money(d.ma200):"—"}</td><td>{d?money(d.all_time_high):"—"}</td><td className={cls(d?.price_vs_ath_percent)}>{d?pct(d.price_vs_ath_percent):"—"}</td><td>{d?ratio(d.price_to_sales_ratio):"—"}</td><td>{d?ratio(d.pe_ratio):"—"}</td><td>{d?ratio(d.peg_ratio):"—"}</td><td className={d?.relative_volume!=null?(d.relative_volume>=1?"positive":"negative"):""}>{d?.relative_volume!=null?`${d.relative_volume.toFixed(2)}x`:"—"}</td><td><button className="btn" disabled={!!loading[s]} onClick={()=>onRefresh(s)}>{loading[s]?"Loading":"Refresh"}</button></td></tr>})}</tbody></table></div>
}
export function MarketCardMetrics({d}:{d:Market}){
 const rows=[
  ["7D",pct(d.seven_day_percent),cls(d.seven_day_percent)],["30D",pct(d.thirty_day_percent),cls(d.thirty_day_percent)],["YTD",pct(d.ytd_percent),cls(d.ytd_percent)],
  ["50MA",money(d.ma50),cls(d.price_vs_ma50_percent)],["100MA",money(d.ma100),cls(d.price_vs_ma100_percent)],["200MA",money(d.ma200),cls(d.price_vs_ma200_percent)],
  ["ATH",money(d.all_time_high),""],["vs ATH",pct(d.price_vs_ath_percent),cls(d.price_vs_ath_percent)],["P/S",ratio(d.price_to_sales_ratio),""],["P/E",ratio(d.pe_ratio),""],["PEG",ratio(d.peg_ratio),""],["Rel Vol",d.relative_volume==null?"—":`${d.relative_volume.toFixed(2)}x`,d.relative_volume==null?"":d.relative_volume>=1?"positive":"negative"]
 ];
 return <div className="metric-grid">{rows.map(([label,value,c])=><span key={label}>{label} <strong className={c}>{value}</strong></span>)}</div>
}
