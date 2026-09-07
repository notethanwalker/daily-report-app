"use client";

import {useEffect,useRef} from "react";

const API="/backend";
async function getLayout(){const r=await fetch(`${API}/api/v1/future/dashboard-layouts`,{cache:"no-store",credentials:"include"});if(!r.ok)return null;const d=await r.json().catch(()=>null);if(!d)return null;return (d.layouts||[]).find((x:any)=>x.name===d.active)||d.layouts?.[0]||null}

function registerReportModules(){
 const sections=Array.from(document.querySelectorAll<HTMLElement>("main.container > .tab-panel"));
 const report=sections.find(x=>x.querySelector(".report-utility"));
 if(!report)return null;
 report.classList.add("dashboard-layout-zone","report-layout-zone");
 const home=report.querySelector<HTMLElement>(":scope > .dashboard-layout-zone:not(.report-layout-zone)");
 if(home){home.classList.remove("dashboard-layout-zone");home.classList.add("home-dashboard-flatten");home.style.display="contents"}
 const set=(selector:string,key:string)=>{const el=report.querySelector<HTMLElement>(selector);if(el)el.dataset.dashboardCard=key};
 set(".report-utility","report_controls");
 set(".report-summary-grid","trust_summary");
 set(".currency-card","currencies");
 const cards=Array.from(report.querySelectorAll<HTMLElement>(".card"));
 for(const card of cards){const heading=(card.querySelector("h2")?.textContent||"").trim();if(heading==="Notable Outliers")card.dataset.dashboardCard="outliers";if(heading==="Top Market News")card.dataset.dashboardCard="top_news"}
 return report;
}

function applyLayout(layout:any){
 const zone=registerReportModules();if(!zone||!layout)return;
 zone.style.setProperty("--dashboard-columns",String(layout.columns||2));zone.dataset.density=layout.density||"comfortable";
 const order=new Map((layout.cards||[]).map((x:string,i:number)=>[x,i]));const hidden=new Set(layout.hidden||[]);
 zone.querySelectorAll<HTMLElement>("[data-dashboard-card]").forEach(el=>{const key=el.dataset.dashboardCard||"";el.style.order=String(order.has(key)?order.get(key):999);el.style.display=hidden.has(key)?"none":""});
}

export default function DashboardLayoutRuntimeV3(){
 const layoutRef=useRef<any>(null);
 useEffect(()=>{let live=true,pending=false;async function refresh(){try{const layout=await getLayout();if(!live)return;layoutRef.current=layout;applyLayout(layout)}catch{}}function schedule(){if(pending)return;pending=true;requestAnimationFrame(()=>{pending=false;applyLayout(layoutRef.current)})}refresh();const observer=new MutationObserver(schedule);observer.observe(document.body,{subtree:true,childList:true});const changed=()=>refresh();window.addEventListener("daily-report-dashboard-layout-changed",changed);window.addEventListener("daily-report-nav-request",schedule);return()=>{live=false;observer.disconnect();window.removeEventListener("daily-report-dashboard-layout-changed",changed);window.removeEventListener("daily-report-nav-request",schedule)}},[]);
 return null;
}
