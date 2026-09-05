"use client";

type Market={symbol:string;price?:number|null;price_vs_ma100_percent?:number|null;price_vs_ma200_percent?:number|null;price_vs_ath_percent?:number|null;williams_r_14?:number|null;price_to_sales_ratio?:number|null;pe_ratio?:number|null;peg_ratio?:number|null;market_cap?:number|null;sector?:string|null};
type FlowEvent={symbol:string;data?:{side?:string|null;aggression?:string|null;premium?:number|null;market_cap?:number|null}};
type RotationRow={symbol:string;name:string;rotation_score:number;seven_day_percent?:number|null};
type Tier="core"|"extended"|"minimal";
type Flag={label:string;value:string;tier:Tier;score:number};

const EXCLUDED=new Set(["QQQ","SPY","SCHD"]);
const pct=(v:number|null|undefined)=>v==null?"—":`${v>=0?"+":""}${v.toFixed(1)}%`;
const ratio=(v:number|null|undefined)=>v==null?"—":v.toFixed(2);
const money=(v:number|null|undefined)=>v==null?"—":v>=1_000_000?`$${(v/1_000_000).toFixed(2)}M`:v>=1_000?`$${(v/1_000).toFixed(0)}K`:`$${v.toFixed(0)}`;

const THEMES:Record<string,string[]>={AAOI:["EUV","SMH"],NBIS:["NCLD","QQQ"],SNDK:["DRAM","SMH"],AXTI:["EUV","SMH"],CRBS:["XBI","XLV"],IONQ:["QTUM"],OKLO:["NLR"],GLD:["GLD"],SMH:["SMH"],BOTZ:["BOTZ"]};
const SECTOR_ETF:Record<string,string>={Technology:"XLK",Financials:"XLF",Energy:"XLE",Healthcare:"XLV",Industrials:"XLI",Materials:"XLB",Utilities:"XLU","Real Estate":"XLRE","Communication Services":"XLC","Consumer Discretionary":"XLY","Consumer Staples":"XLP"};

function execution(v:string|null|undefined){const s=(v||"").toLowerCase();if(s.includes("buy")||s.includes("ask")||s.includes("lift"))return"buy";if(s.includes("sell")||s.includes("bid")||s.includes("hit"))return"sell";return"unknown"}
function flowBias(e:FlowEvent){const side=(e.data?.side||"").toLowerCase(),ex=execution(e.data?.aggression);if((side==="call"&&ex==="buy")||(side==="put"&&ex==="sell"))return"bull";if((side==="call"&&ex==="sell")||(side==="put"&&ex==="buy"))return"bear";return"neutral"}
function bestFlow(events:FlowEvent[],symbol:string,bias:"bull"|"bear",fallbackCap?:number|null){const rows=events.filter(e=>e.symbol===symbol&&flowBias(e)===bias);let best:{premium:number;relative:number}|null=null;for(const e of rows){const premium=e.data?.premium||0,cap=e.data?.market_cap||fallbackCap||0,relative=cap>0?premium/cap:0;if(!best||premium>best.premium)best={premium,relative}}return best}
function flowTier(flow:{premium:number;relative:number}|null){if(!flow)return null;if(flow.premium>=250_000||flow.relative>=0.0001)return"core" as Tier;if(flow.premium>=100_000||flow.relative>=0.00005)return"extended" as Tier;if(flow.premium>=50_000||flow.relative>=0.000025)return"minimal" as Tier;return null}
function relatedSector(symbol:string,m:Market,sectors:RotationRow[]){const bySymbol=new Map(sectors.map(x=>[x.symbol,x]));const candidates=[...(THEMES[symbol]||[])];if(m.sector&&SECTOR_ETF[m.sector])candidates.push(SECTOR_ETF[m.sector]);if(bySymbol.has(symbol))candidates.push(symbol);const matches=candidates.map(s=>bySymbol.get(s)).filter(Boolean) as RotationRow[];if(!matches.length)return null;return matches.sort((a,b)=>Math.abs(b.rotation_score)-Math.abs(a.rotation_score))[0]}
function points(tier:Tier,isWilliams=false){return tier==="core"?(isWilliams?4:3):tier==="extended"?2:1}
function addTiered(flags:Flag[],core:boolean,weak:boolean,minimal:boolean,label:string,value:string,isWilliams=false){const tier:Tier|null=core?"core":weak?"extended":minimal?"minimal":null;if(tier)flags.push({label,value,tier,score:points(tier,isWilliams)})}

function buildFlags(tickers:string[],market:Record<string,Market>,rotation:any,events:FlowEvent[],kind:"buy"|"sell"){
 const sectors:RotationRow[]=rotation?.sectors||[];
 return tickers.filter(symbol=>!EXCLUDED.has(symbol)).map(symbol=>{const m=market[symbol];if(!m)return null;const flags:Flag[]=[];const rel=relatedSector(symbol,m,sectors);const bull=bestFlow(events,symbol,"bull",m.market_cap),bear=bestFlow(events,symbol,"bear",m.market_cap);
  if(kind==="buy"){
   if(m.price_vs_ma100_percent!=null)addTiered(flags,Math.abs(m.price_vs_ma100_percent)<=10,Math.abs(m.price_vs_ma100_percent)<=15,Math.abs(m.price_vs_ma100_percent)<=20,"Near 100MA",pct(m.price_vs_ma100_percent));
   if(m.price_vs_ma200_percent!=null)addTiered(flags,Math.abs(m.price_vs_ma200_percent)<=10,Math.abs(m.price_vs_ma200_percent)<=15,Math.abs(m.price_vs_ma200_percent)<=20,"Near 200MA",pct(m.price_vs_ma200_percent));
   if(m.williams_r_14!=null)addTiered(flags,m.williams_r_14<=-80,m.williams_r_14<=-65,m.williams_r_14<=-50,"Low Williams %R",m.williams_r_14.toFixed(1),true);
   if(m.price_to_sales_ratio!=null)addTiered(flags,m.price_to_sales_ratio<=3,m.price_to_sales_ratio<=5,m.price_to_sales_ratio<=8,"Low P/S",ratio(m.price_to_sales_ratio));
   if(m.pe_ratio!=null&&m.pe_ratio>0)addTiered(flags,m.pe_ratio<=20,m.pe_ratio<=30,m.pe_ratio<=40,"Low P/E",ratio(m.pe_ratio));
   if(m.peg_ratio!=null&&m.peg_ratio>0)addTiered(flags,m.peg_ratio<=1.5,m.peg_ratio<=2,m.peg_ratio<=3,"Low PEG",ratio(m.peg_ratio));
   if(rel)addTiered(flags,rel.rotation_score>=1,rel.rotation_score>=0.25,rel.rotation_score>=0,`Sector strength · ${rel.symbol}`,`${rel.rotation_score>=0?"+":""}${rel.rotation_score.toFixed(2)}`);
   const bt=flowTier(bull);if(bull&&bt)flags.push({label:"Large bullish flow",value:`${money(bull.premium)}${bull.relative?` · ${(bull.relative*10000).toFixed(2)} bps`:""}`,tier:bt,score:points(bt)});
  }else{
   if(m.price_vs_ath_percent!=null)addTiered(flags,m.price_vs_ath_percent>=-10,m.price_vs_ath_percent>=-15,m.price_vs_ath_percent>=-20,"Near ATH",pct(m.price_vs_ath_percent));
   if(m.williams_r_14!=null)addTiered(flags,m.williams_r_14>=-20,m.williams_r_14>=-35,m.williams_r_14>=-50,"High Williams %R",m.williams_r_14.toFixed(1),true);
   if(m.price_to_sales_ratio!=null)addTiered(flags,m.price_to_sales_ratio>=10,m.price_to_sales_ratio>=7,m.price_to_sales_ratio>=5,"High P/S",ratio(m.price_to_sales_ratio));
   if(m.pe_ratio!=null&&m.pe_ratio>0)addTiered(flags,m.pe_ratio>=40,m.pe_ratio>=30,m.pe_ratio>=25,"High P/E",ratio(m.pe_ratio));
   if(rel)addTiered(flags,rel.rotation_score<=-1,rel.rotation_score<=-0.25,rel.rotation_score<=0,`Sector weakness · ${rel.symbol}`,`${rel.rotation_score>=0?"+":""}${rel.rotation_score.toFixed(2)}`);
   const st=flowTier(bear);if(bear&&st)flags.push({label:"Large bearish flow",value:`${money(bear.premium)}${bear.relative?` · ${(bear.relative*10000).toFixed(2)} bps`:""}`,tier:st,score:points(st)});
  }
  const core=flags.filter(f=>f.tier==="core").length,extended=flags.filter(f=>f.tier==="extended").length,minimal=flags.filter(f=>f.tier==="minimal").length,score=flags.reduce((sum,f)=>sum+f.score,0);
  return flags.length?{symbol,flags,core,extended,minimal,score}:null}).filter(Boolean).sort((a:any,b:any)=>b.score-a.score||b.core-a.core||b.extended-a.extended) as {symbol:string;flags:Flag[];core:number;extended:number;minimal:number;score:number}[];
}

function FlagGrid({title,tone,rows}:{title:string;tone:"buy"|"sell";rows:{symbol:string;flags:Flag[];core:number;extended:number;minimal:number;score:number}[]}){
 return <div className={`card reveal-card flag-card ${tone}`}><div className="section-head"><div><span className="eyebrow">Signal checklist</span><h2>{title}</h2></div><span className="reason-count">{rows.length} tickers</span></div><div className="flag-tier-legend"><span className="flag-legend-core">Strong flag</span><span className="flag-legend-extended">Weak flag</span><span className="flag-legend-minimal">Minimal flag</span></div><div className="flag-grid-head"><span>Ticker</span><span>Matched flags</span><span>Score</span></div><div className="flag-grid-body">{rows.length?rows.map(r=><div className="flag-grid-row" key={r.symbol}><strong>{r.symbol}</strong><div className="flag-chip-wrap">{r.flags.map(f=><span className={`flag-chip ${f.tier}`} key={`${r.symbol}-${f.label}`} title={`+${f.score} score`}><b>{f.label}</b><i>{f.value}</i></span>)}</div><strong title={`${r.core} strong · ${r.extended} weak · ${r.minimal} minimal`}>{r.score}<small className="flag-count-detail">{r.core}S/{r.extended}W/{r.minimal}M</small></strong></div>):<p className="muted flag-empty">No tracked ticker currently meets a flag tier.</p>}</div></div>;
}

export default function MarketFlags({tickers,market,rotation,flowEvents}:{tickers:string[];market:Record<string,Market>;rotation:any;flowEvents:FlowEvent[]}){
 const buys=buildFlags(tickers,market,rotation,flowEvents,"buy"),sells=buildFlags(tickers,market,rotation,flowEvents,"sell");
 return <section className="market-flags-section"><div className="card reveal-card flags-method"><span className="eyebrow">Cross-tab intelligence</span><h2>Buy / Sell Flags</h2><p className="muted"><strong>Strong</strong>, <strong>Weak</strong>, and <strong>Minimal</strong> flags use progressively broader thresholds. QQQ, SPY and SCHD are excluded. Ranking score: strong Williams %R = +4, every other strong flag = +3, weak flag = +2, minimal flag = +1. Minimal buy thresholds: MA ±20%, Williams ≤ -50, P/S ≤ 8, P/E ≤ 40, PEG ≤ 3, non-negative sector score, or bullish flow ≥ $50K / 0.25 bp. Minimal sell thresholds: within 20% of ATH, Williams ≥ -50, P/S ≥ 5, P/E ≥ 25, non-positive sector score, or bearish flow ≥ $50K / 0.25 bp. Flags are screening conditions, not trade recommendations.</p></div><div className="flags-layout"><FlagGrid title="Buy Flags" tone="buy" rows={buys}/><FlagGrid title="Sell Flags" tone="sell" rows={sells}/></div></section>;
}
