"use client";

import {useEffect,useState} from "react";

const API="/backend";
async function api(path:string,options:RequestInit={}){const r=await fetch(`${API}${path}`,{cache:"no-store",credentials:"include",...options,headers:{...(options.headers||{})}});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d?.detail||`HTTP ${r.status}`);return d}

export type AccessState={email:string;role:string;enabled:boolean;permissions:Record<string,boolean>;allowed_tabs:string[];preferences:{visible_tabs:string[];information_modules:Record<string,boolean>;settings:Record<string,any>};auth_enabled:boolean};

export function useUserAccess(){const[data,setData]=useState<AccessState|null>(null),[error,setError]=useState("");async function load(){try{setData(await api("/api/v1/user/access"));setError("")}catch(e:any){setError(e.message)}}useEffect(()=>{load();const h=()=>load();window.addEventListener("daily-report-session-changed",h);return()=>window.removeEventListener("daily-report-session-changed",h)},[]);return{data,error,reload:load}}

export function applyUserVisibility(access:AccessState|null){if(!access)return;const visible=new Set(access.preferences.visible_tabs?.length?access.preferences.visible_tabs:access.allowed_tabs);document.querySelectorAll<HTMLButtonElement>(".nav button").forEach(btn=>{const name=(btn.textContent||"").trim();btn.style.display=visible.has(name)?"":"none"});const mods=access.preferences.information_modules||{};document.querySelectorAll<HTMLElement>("[data-info-module]").forEach(el=>{const key=el.dataset.infoModule||"";el.style.display=mods[key]===false?"none":""});const context=document.querySelector<HTMLElement>(".context-bar");if(context)context.style.display=mods.context_bar===false?"none":""}

export function UserCustomizationPanel({access,onChanged}:{access:AccessState;onChanged:()=>void}){
 const[tabs,setTabs]=useState<string[]>(access.preferences.visible_tabs||[]),[mods,setMods]=useState<Record<string,boolean>>(access.preferences.information_modules||{}),[saving,setSaving]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState("");
 useEffect(()=>{setTabs(access.preferences.visible_tabs||[]);setMods(access.preferences.information_modules||{})},[access]);
 async function save(){setSaving(true);setError("");setNotice("");try{await api("/api/v1/user/preferences",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({visible_tabs:tabs,information_modules:mods})});setNotice("Layout preferences saved.");onChanged()}catch(e:any){setError(e.message)}finally{setSaving(false)}}
 const canTabs=!!access.permissions.can_customize_tabs,canInfo=!!access.permissions.can_customize_information;
 return <div className="card reveal-card user-customization-card"><div className="section-head"><div><span className="eyebrow">Private user layout</span><h2>My Tabs & Information</h2></div></div><p className="muted">These choices are stored for this account only. Authentication credentials are managed separately under Account & security.</p>{canTabs&&<fieldset><legend>Visible tabs</legend><div className="permission-grid">{access.allowed_tabs.map(t=><label key={t}><input type="checkbox" checked={tabs.includes(t)} onChange={e=>setTabs(x=>e.target.checked?[...x,t]:x.filter(v=>v!==t))}/><span>{t}</span></label>)}</div></fieldset>}{canInfo&&<fieldset><legend>Information modules</legend><div className="permission-grid">{Object.keys(mods).map(k=><label key={k}><input type="checkbox" checked={mods[k]!==false} onChange={e=>setMods(x=>({...x,[k]:e.target.checked}))}/><span>{k.replaceAll("_"," ")}</span></label>)}</div></fieldset>}{(canTabs||canInfo)&&<button className="btn" onClick={save} disabled={saving} aria-busy={saving}>{saving?"Saving…":"Save my layout"}</button>}<div className="sr-only" role="status" aria-live="polite" aria-atomic="true">{saving?"Saving layout preferences…":notice}</div>{notice&&<p className="positive" aria-hidden="true">{notice}</p>}{error&&<p className="negative" role="alert" aria-live="assertive">{error}</p>}</div>
}

export function AdminUserPanel(){return <div className="card reveal-card"><span className="eyebrow">Administrator</span><h2>User access</h2><p className="muted">Account approval, rejection and credential management now use the encrypted account system in Account & security above. Legacy access tokens are disabled.</p></div>}
