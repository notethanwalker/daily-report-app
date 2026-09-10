"use client";

import {useEffect} from "react";
import Link from "next/link";
import {useRouter} from "next/navigation";
import {AuthGate,type Account} from "../../auth-shell";
import GlobalTickerSearchV4 from "../global-ticker-search-v4";

function routeFor(detail:any){
 const tab=typeof detail==="string"?detail:detail?.tab;
 const symbol=typeof detail==="object"?String(detail?.symbol||"").trim().toUpperCase():"";
 if((tab==="Research"||tab==="Markets")&&symbol)return `/v4/deep/research/${encodeURIComponent(symbol)}`;
 const routes:Record<string,string>={"World News":"/v4/deep/world-news",Events:"/v4/deep/events","Large Flow":"/v4/deep/flow",Portfolio:"/v4/deep/portfolio",Research:"/v4",Markets:"/v4"};
 return routes[tab]||"";
}

export default function DeepShell({title,layer,description,children}:{title:string;layer:string;description:string;children:(account:Account)=>React.ReactNode}){
 const router=useRouter();
 useEffect(()=>{const onNav=(event:Event)=>{const target=routeFor((event as CustomEvent).detail);if(target)router.push(target)};window.addEventListener("daily-report-nav-request",onNav);return()=>window.removeEventListener("daily-report-nav-request",onNav)},[router]);
 return <AuthGate>{account=><main className="v4-shell deep-v4-shell"><header className="v4-header"><div><span className="v4-kicker">{layer} · EXPANDED DETAIL</span><h1>{title}</h1><p>{description}</p></div><div className="v4-user"><span>{account.name}</span><GlobalTickerSearchV4 compact/><nav aria-label="Deep workspace navigation"><Link className="source-link" href="/v4">← Decision Stack</Link></nav></div></header><section className="deep-v4-body" aria-label={`${title} workspace`}>{children(account)}</section></main>}</AuthGate>
}
