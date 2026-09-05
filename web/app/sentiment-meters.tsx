"use client";
import {useEffect,useState} from "react";
import styles from "./report-additions.module.css";

type Meter={id:string;name:string;score:number;label:string;detail:string;source_url:string;scale:string;as_of?:string|null};

export default function SentimentMeters(){
 const[meters,setMeters]=useState<Meter[]>([]),[error,setError]=useState("");
 useEffect(()=>{let live=true;(async()=>{try{const r=await fetch("/api/sentiment",{cache:"no-store"});const d=await r.json();if(!r.ok)throw new Error("Sentiment sources unavailable");if(live)setMeters(d.meters||[])}catch(e:any){if(live)setError(e?.message||"Sentiment sources unavailable")}})();return()=>{live=false}},[]);
 if(error&&!meters.length)return <div className={`card reveal-card ${styles.empty}`}><strong>External sentiment meters unavailable</strong><span>{error}</span></div>;
 return <div className={styles.sourceGrid}>{meters.map(m=><a className={`card reveal-card ${styles.sourceCard}`} href={m.source_url} target="_blank" rel="noreferrer" key={m.id}><div className={styles.sourceHead}><div><span className="eyebrow">{m.name}</span><strong>{m.label}</strong></div><span>{m.score.toFixed(0)}</span></div><div className={styles.bar}><i style={{width:`${Math.max(0,Math.min(100,m.score))}%`}}/></div><p>{m.detail}</p><small>{m.scale}{m.as_of?` · ${m.as_of}`:""}</small></a>)}</div>;
}
