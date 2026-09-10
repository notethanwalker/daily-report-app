"use client";

import {useEffect,useMemo,useState} from "react";

type CardState={id:string;label:string;hidden:boolean;order:number};
const KEY="dailyReportV4CardLayouts";
function stored(){try{return JSON.parse(localStorage.getItem(KEY)||"{}")||{}}catch{return {}}}
function layerName(){return (document.querySelector(".v4-pipeline button.active strong")?.textContent||"").trim().toLowerCase()}
function cardLabel(el:HTMLElement,i:number){return (el.dataset.cardLabel||el.querySelector("h2")?.textContent||el.querySelector(".label")?.textContent||`Card ${i+1}`).trim()}
function slug(v:string){return v.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"")||"card"}
function inventory(layer:string){const seen=new Map<string,number>();return Array.from(document.querySelectorAll<HTMLElement>(".v4-grid > .v4-card")).map((el,i)=>{const label=cardLabel(el,i),base=el.dataset.cardId?.trim()||`${layer}:${slug(label)}`,count=seen.get(base)||0;seen.set(base,count+1);const id=count?`${base}:${count+1}`:base;return{el,id,label,index:i}})}
function apply(layer:string){if(!layer)return;const cfg=stored()[layer]||{};inventory(layer).forEach(({el,id,index})=>{const c=cfg[id];el.style.order=String(c?.order??index);el.style.display=c?.hidden?"none":""})}

export default function V4CardLayoutHost(){
 const[layer,setLayer]=useState(""),[cards,setCards]=useState<CardState[]>([]),[open,setOpen]=useState(false);
 function sync(){const l=layerName();setLayer(l);if(!l){setCards([]);return}const cfg=stored()[l]||{};const next=inventory(l).map(({id,label,index})=>{const c=cfg[id];return{id,label,hidden:!!c?.hidden,order:Number(c?.order??index)}}).sort((a,b)=>a.order-b.order);setCards(next);apply(l)}
 useEffect(()=>{sync();let queued=false;const schedule=()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;sync()})};const observer=new MutationObserver(schedule);observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:["class","data-card-id","data-card-label"]});return()=>observer.disconnect()},[]);
 const visible=useMemo(()=>!!layer&&cards.length>0,[layer,cards.length]);
 function save(next:CardState[]){const all=stored(),cfg:any={};next.forEach((c,i)=>cfg[c.id]={hidden:c.hidden,order:i});all[layer]=cfg;localStorage.setItem(KEY,JSON.stringify(all));setCards(next.map((c,i)=>({...c,order:i})));requestAnimationFrame(()=>apply(layer))}
 function toggle(id:string){save(cards.map(c=>c.id===id?{...c,hidden:!c.hidden}:c))}
 function move(id:string,dir:number){const a=[...cards],i=a.findIndex(c=>c.id===id),j=i+dir;if(i<0||j<0||j>=a.length)return;[a[i],a[j]]=[a[j],a[i]];save(a)}
 function reset(){const all=stored();delete all[layer];localStorage.setItem(KEY,JSON.stringify(all));Array.from(document.querySelectorAll<HTMLElement>(".v4-grid > .v4-card")).forEach(el=>{el.style.order="";el.style.display=""});sync()}
 if(!visible)return null;
 return <aside className={`v4-card-layout-host ${open?"open":""}`} aria-label="Current layer card layout"><button className="v4-layout-toggle" type="button" aria-expanded={open} onClick={()=>setOpen(x=>!x)}>Layout</button>{open&&<div className="v4-layout-panel"><strong>{layer[0].toUpperCase()+layer.slice(1)} cards</strong><span>Reorder or hide cards on this device.</span>{cards.map((c,i)=><div className="v4-layout-row" key={c.id}><button type="button" aria-pressed={!c.hidden} onClick={()=>toggle(c.id)}>{c.hidden?"Show":"Hide"}</button><b>{c.label}</b><button type="button" aria-label={`Move ${c.label} up`} disabled={i===0} onClick={()=>move(c.id,-1)}>↑</button><button type="button" aria-label={`Move ${c.label} down`} disabled={i===cards.length-1} onClick={()=>move(c.id,1)}>↓</button></div>)}<button type="button" className="v4-layout-reset" onClick={reset}>Reset layer</button></div>}</aside>
}
