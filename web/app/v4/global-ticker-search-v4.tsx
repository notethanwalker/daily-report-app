"use client";

import {FormEvent,useState} from "react";

export default function GlobalTickerSearchV4({onOpen,compact=false}:{onOpen?:(symbol:string)=>void;compact?:boolean}){
 const[query,setQuery]=useState("");
 function submit(e:FormEvent){e.preventDefault();const symbol=query.trim().toUpperCase();if(!symbol)return;if(onOpen){onOpen(symbol);setQuery("");return}window.location.assign(`/?symbol=${encodeURIComponent(symbol)}`)}
 return <form className={`global-ticker-search-v4 ${compact?"compact":""}`} onSubmit={submit} role="search"><label className="sr-only" htmlFor={compact?"global-ticker-deep":"global-ticker-root"}>Global ticker search</label><input id={compact?"global-ticker-deep":"global-ticker-root"} value={query} onChange={e=>setQuery(e.target.value.toUpperCase().replace(/[^A-Z0-9.\-]/g,""))} maxLength={12} autoCapitalize="characters" autoCorrect="off" spellCheck={false} placeholder="Ticker" aria-label="Global ticker search"/><button type="submit" disabled={!query.trim()}>Research</button></form>
}
