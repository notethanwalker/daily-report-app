"use client";

type Market={symbol:string;price?:number|null;price_vs_ma100_percent?:number|null;price_vs_ma200_percent?:number|null;price_vs_ath_percent?:number|null;williams_r_14?:number|null;price_to_sales_ratio?:number|null;pe_ratio?:number|null;peg_ratio?:number|null;market_cap?:number|null;sector?:string|null};
type FlowEvent={symbol:string;data?:{side?:string|null;aggression?:string|null;premium?:number|null;market_cap?:number|null}};
type RotationRow={symbol:string;name:string;rotation_score:number;seven_day_percent?:number|null};

type Flag={label:string;value:string};
const pct=(v:number|null|undefined)=>v==null?"—":`${v>=0?"+":""}${v.toFixed(1)}%`;
const ratio=(v:number|null|undefined)=>v==null?"—":v.toFixed(2);
const money=(v:number|null|undefined)=>v==null?"—":v>=1_000_000?`$${(v/1_000_000).toFixed(2)}M`:v>=1_000?`$${(v/1_000).toFixed(0)}K`:`$${v.toFixed(0)}`;

const THEMES:Record<string,string[]>={
 AAOI:["EUV","SMH"],NBIS:["NCLD","QQQ"],SNDK:["DRAM","SMH"],AXTI:["EUV","SMH"],CRBS:["XBI","XLV"],IONQ:["QTUM"],OKLO:["NLR"],GLD:["GLD"],SMH:["SMH"],BOTZ:["BOTZ"],SPY:["SPY"],QQQ:["QQQ"],
};
const SECTOR_ETF:Record<string,string>={Technology:"XLK",Financials:"XLF",Energy:"XLE",Healthcare:"XLV",Industrials:"XLI",Materials:"XLB",Utilities:"XLU","Real Estate":"XLRE","Communication Services":"XLC","Consumer Discretionary":"XLY","Consumer Staples":"XLP"};

function execution(v:string|null|undefined){const s=(v||"").toLowerCase();if(s.includes("buy")||s.includes("ask")||s.includes("lift"))return"buy";if(s.includes("sell")||s.includes("bid")||s.includes("hit"))return"sell";return"unknown"}
function flowBias(e:FlowEvent){const side=(e.data?.side||"").toLowerCase(),ex=execution(e.data?.aggression);if((side==="call"&&ex==="buy")||(side==="put"&&ex==="sell"))return"bull";if((side==="call"&&ex==="sell")||(side==="put"&&ex==="buy"))return"bear";return"neutral"}
function largeFlow(events:FlowEvent[],symbol:string,bias:"bull"|"bear",fallbackCap?:number|null){const rows=events.filter(e=>e.symbol===symbol&&flowBias(e)===bias);let best:{premium:number;relative:number}|null=null;for(const e of rows){const premium=e.data?.premium||0,cap=e.data?.market_cap||fallbackCap||0,relative=cap>0?premium/cap:0;if(premium>=250_000||relative>=0.0001){if(!best||premium>best.premium)best={premium,relative}}}return best}
function relatedSector(symbol:string,m:Market,sectors:RotationRow[]){const bySymbol=new Map(sectors.map(x=>[x.symbol,x]));const candidates=[...(THEMES[symbol]||[])];if(m.sector&&SECTOR_ETF[m.sector])candidates.push(SECTOR_ETF[m.sector]);if(bySymbol.has(symbol))candidates.push(symbol);const matches=candidates.map(s=>bySymbol.get(s)).filter(Boolean) as RotationRow[];if(!matches.length)return null;return matches.sort((a,b)=>Math.abs(b.rotation_score)-Math.abs(a.rotation_score))[0]}

function buildFlags(tickers:string[],market:Record<string,Market>,rotation:any,events:FlowEvent[],kind:"buy"|"sell"){
 const sectors:RotationRow[]=rotation?.sectors||[];
 return tickers.map(symbol=>{const m=market[symbol];if(!m)return null;const flags:Flag[]=[];const rel=relatedSector(symbol,m,sectors);const bull=largeFlow(events,symbol,"bull",m.market_cap),bear=largeFlow(events,symbol,"bear",m.market_cap);
  if(kind==="buy"){
   if(m.price_vs_ma100_percent!=null&&Math.abs(m.price_vs_ma100_percent)<=10)flags.push({label:"Near 100MA",value:pct(m.price_vs_ma100_percent)});
   if(m.price_vs_ma200_percent!=null&&Math.abs(m.price_vs_ma200_percent)<=10)flags.push({label:"Near 200MA",value:pct(m.price_vs_ma200_percent)});
   if(m.williams_r_14!=null&&m.williams_r_14<=-80)flags.push({label:"Low Williams %R",value:m.williams_r_14.toFixed(1)});
   if(m.price_to_sales_ratio!=null&&m.price_to_sales_ratio<=3)flags.push({label:"Low P/S",value:ratio(m.price_to_sales_ratio)});
   if(m.pe_ratio!=null&&m.pe_ratio>0&&m.pe_ratio<=20)flags.push({label:"Low P/E",value:ratio(m.pe_ratio)});
   if(m.peg_ratio!=null&&m.peg_ratio>0&&m.peg_ratio<=1.5)flags.push({label:"Low PEG",value:ratio(m.peg_ratio)});
   if(rel&&rel.rotation_score>=1)flags.push({label:`Sector strength · ${rel.symbol}`,value:`${rel.rotation_score>=0?"+":""}${rel.rotation_score.toFixed(2)}`});
   if(bull)flags.push({label:"Large bullish flow",value:`${money(bull.premium)}${bull.relative?` · ${(bull.relative*10000).toFixed(2)} bps`:""}`});
  }else{
   if(m.price_vs_ath_percent!=null&&m.price_vs_ath_percent>=-10)flags.push({label:"Near ATH",value:pct(m.price_vs_ath_percent)});
   if(m.williams_r_14!=null&&m.williams_r_14>=-20)flags.push({label:"High Williams %R",value:m.williams_r_14.toFixed(1)});
   if(m.price_to_sales_ratio!=null&&m.price_to_sales_ratio>=10)flags.push({label:"High P/S",value:ratio(m.price_to_sales_ratio)});
   if(m.pe_ratio!=null&&m.pe_ratio>=40)flags.push({label:"High P/E",value:ratio(m.pe_ratio)});
   if(rel&&rel.rotation_score>=1)flags.push({label:`Related sector strength · ${rel.symbol}`,value:`${rel.rotation_score>=0?"+":""}${rel.rotation_score.toFixed(2)}`});
   if(bear)flags.push({label:"Large bearish flow",value:`${money(bear.premium)}${bear.relative?` · ${(bear.relative*10000).toFixed(2)} bps`:""}`});
  }
  return flags.length?{symbol,flags}:null}).filter(Boolean).sort((a:any,b:any)=>b.flags.length-a.flags.length) as {symbol:string;flags:Flag[]}[];
}

function FlagGrid({title,tone,rows}:{title:string;tone:"buy"|"sell";rows:{symbol:string;flags:Flag[]}[]}){
 return <div className={`card reveal-card flag-card ${tone}`}><div className="section-head"><div><span className="eyebrow">Signal checklist</span><h2>{title}</h2></div><span className="reason-count">{rows.length} tickers</span></div><div className="flag-grid-head"><span>Ticker</span><span>Matched flags</span><span>Count</span></div><div className="flag-grid-body">{rows.length?rows.map(r=><div className="flag-grid-row" key={r.symbol}><strong>{r.symbol}</strong><div className="flag-chip-wrap">{r.flags.map(f=><span className="flag-chip" key={`${r.symbol}-${f.label}`}><b>{f.label}</b><i>{f.value}</i></span>)}</div><strong>{r.flags.length}</strong></div>):<p className="muted flag-empty">No tracked ticker currently meets these thresholds.</p>}</div></div>;
}

export default function MarketFlags({tickers,market,rotation,flowEvents}:{tickers:string[];market:Record<string,Market>;rotation:any;flowEvents:FlowEvent[]}){
 const buys=buildFlags(tickers,market,rotation,flowEvents,"buy"),sells=buildFlags(tickers,market,rotation,flowEvents,"sell");
 return <section className="market-flags-section"><div className="card reveal-card flags-method"><span className="eyebrow">Cross-tab intelligence</span><h2>Buy / Sell Flags</h2><p className="muted">Uses the same cached market snapshot, valuation cache, macro rotation data and shared Large Flow response already loaded elsewhere in the app. Thresholds: MA proximity ±10%; Williams oversold ≤ -80 / overbought ≥ -20; low P/S ≤ 3, P/E ≤ 20, PEG ≤ 1.5; high P/S ≥ 10, P/E ≥ 40; large flow ≥ $250K premium or ≥ 1 bp of market cap. Flags are screening conditions, not trade recommendations.</p></div><div className="flags-layout"><FlagGrid title="Buy Flags" tone="buy" rows={buys}/><FlagGrid title="Sell Flags" tone="sell" rows={sells}/></div></section>;
}
