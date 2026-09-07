"use client";
import {useEffect,useMemo,useRef,useState} from "react";

const API="/backend";
const NON_COMPANY=new Set(["SPY","QQQ","GLD","SMH","EUV","DRAM","BOTZ","VIX"]);
type Market={pe_ratio?:number|null;peg_ratio?:number|null;price_to_sales_ratio?:number|null};

export default function ValuationWarmup({active,tickers,market,onEnrich}:{active:boolean;tickers:string[];market:Record<string,Market>;onEnrich:(symbol:string,data:any)=>void}){
 const[done,setDone]=useState(0),[status,setStatus]=useState("Idle"),[error,setError]=useState("");const running=useRef(false);
 const missing=useMemo(()=>tickers.filter(s=>!NON_COMPANY.has(s)&&!(market[s]?.pe_ratio!=null||market[s]?.peg_ratio!=null||market[s]?.price_to_sales_ratio!=null)),[tickers,market]);
 useEffect(()=>{if(!active||running.current||!missing.length)return;let cancelled=false;running.current=true;setStatus(`Populating ${missing.length} missing company valuations…`);setError("");(async()=>{let completed=0;for(const symbol of missing){if(cancelled)break;try{const r=await fetch(`${API}/api/v1/markets/${encodeURIComponent(symbol)}/fundamentals`,{cache:"no-store",credentials:"include"});const d=await r.json();if(r.ok){onEnrich(symbol,d);completed++;setDone(x=>x+1)}else if(r.status===429){setError("Free fundamentals budget reached for today; cached values remain available and the weekday refresh will continue filling the cache.");break}else if(r.status===502){completed++;setDone(x=>x+1)}else{throw new Error(d?.detail||`HTTP ${r.status}`)}}catch(e:any){setError(e?.message||"Valuation refresh failed");break}if(!cancelled)await new Promise(resolve=>setTimeout(resolve,13000))}if(!cancelled)setStatus(completed?`Valuation cache updated for ${completed} ticker${completed===1?"":"s"}.`:"Valuation cache checked.");running.current=false})();return()=>{cancelled=true;running.current=false}},[active,missing.join("|")]);
 if(!active)return null;
 return <div className="card reveal-card valuation-status"><div><span className="eyebrow">Valuation cache</span><strong>{missing.length?status:"P/S, P/E and PEG cache is populated for available company fundamentals."}</strong></div><span className={error?"negative":"muted"}>{error||`${done} refreshed this session · persistent shared fundamentals cache`}</span></div>;
}
