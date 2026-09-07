"use client";

import {useEffect,useRef} from "react";

const API="/backend";
async function getLayout(){const r=await fetch(`${API}/api/v1/future/dashboard-layouts`,{cache:"no-store",credentials:"include"});if(!r.ok)return null;const d=await r.json().catch(()=>null);if(!d)return null;return (d.layouts||[]).find((x:any)=>x.name===d.active)||d.layouts?.[0]||null}
function applyLayout(layout:any){const zone=document.querySelector<HTMLElement>(".dashboard-layout-zone");if(!zone||!layout)return;zone.style.setProperty("--dashboard-columns",String(layout.columns||2));zone.dataset.density=layout.density||"comfortable";const order=new Map((layout.cards||[]).map((x:string,i:number)=>[x,i]));const hidden=new Set(layout.hidden||[]);zone.querySelectorAll<HTMLElement>("[data-dashboard-card]").forEach(el=>{const key=el.dataset.dashboardCard||"";el.style.order=String(order.has(key)?order.get(key):999);el.style.display=hidden.has(key)?"none":""})}

export default function DashboardLayoutRuntimeV2(){
 const layoutRef=useRef<any>(null);
 useEffect(()=>{let live=true;let pending=false;async function refresh(){try{const layout=await getLayout();if(!live)return;layoutRef.current=layout;applyLayout(layout)}catch{}}function schedule(){if(pending)return;pending=true;requestAnimationFrame(()=>{pending=false;applyLayout(layoutRef.current)})}refresh();const observer=new MutationObserver(schedule);observer.observe(document.body,{subtree:true,childList:true});const changed=()=>refresh();window.addEventListener("daily-report-dashboard-layout-changed",changed);window.addEventListener("daily-report-nav-request",schedule);return()=>{live=false;observer.disconnect();window.removeEventListener("daily-report-dashboard-layout-changed",changed);window.removeEventListener("daily-report-nav-request",schedule)}},[]);
 return null
}
