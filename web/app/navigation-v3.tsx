"use client";

import {useEffect} from "react";
import type {AccessState} from "./user-customization";

const GROUPS=[
 {label:"Daily",items:["Report","Markets","Portfolio"]},
 {label:"Analysis",items:["Opportunities","Research","Macro","Regime"]},
 {label:"Intelligence",items:["World News","Events","Large Flow"]},
 {label:"Monitor",items:["Alerts","Theses"]},
 {label:"System",items:["Settings"]},
];

function directOriginal(nav:Element,name:string){return Array.from(nav.children).find(x=>x.tagName==="BUTTON"&&(x.textContent||"").trim()===name) as HTMLButtonElement|undefined}

export default function GroupedNavigation({nav,active,commandActive,access,onCommand}:{nav:Element;active:string;commandActive:boolean;access:AccessState|null;onCommand:()=>void}){
 useEffect(()=>{nav.classList.add("nav-v3-ready");return()=>nav.classList.remove("nav-v3-ready")},[nav]);
 const visible=new Set(access?.preferences?.visible_tabs?.length?access.preferences.visible_tabs:access?.allowed_tabs||["Command Center","Report","Markets","Portfolio","Opportunities","World News","Events","Large Flow","Macro","Regime","Research","Alerts","Theses","Settings"]);
 function select(name:string,e?:React.MouseEvent){e?.currentTarget.closest("details")?.removeAttribute("open");if(name==="Command Center"){onCommand();return}directOriginal(nav,name)?.click()}
 return <div className="nav-v3" aria-label="Primary navigation">
   {visible.has("Command Center")&&<button className={`nav-command ${commandActive?"active":""}`} onClick={e=>select("Command Center",e)}>Command Center</button>}
   {GROUPS.map(group=>{const items=group.items.filter(x=>visible.has(x));if(!items.length)return null;const selected=!commandActive&&items.includes(active);return <details className={`nav-group ${selected?"active-group":""}`} key={group.label}><summary>{group.label}{selected&&<span>{active}</span>}<b>▾</b></summary><div className="nav-menu">{items.map(item=><button key={item} className={!commandActive&&active===item?"active":""} onClick={e=>select(item,e)}>{item}</button>)}</div></details>})}
 </div>
}
