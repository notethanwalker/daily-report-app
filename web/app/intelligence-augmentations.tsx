"use client";
import {useEffect,useRef,useState} from "react";
import {createPortal} from "react-dom";
import {AlertEventPanel,SecurityDrawer} from "./intelligence-extras";
import PortfolioWorkspaceV3 from "./portfolio-workspace-v3";
import EventsWorkspaceV3 from "./events-workspace-v3";
import OpportunitiesWorkspaceV3 from "./opportunities-workspace-v3";
import ResearchWorkspaceV3 from "./research-workspace-v3";
import MacroWorkspaceV3 from "./macro-workspace-v3";
import LargeFlowWorkspaceV3 from "./large-flow-workspace-v3";
import CommandCenterPanel from "./command-center-v3";
import GroupedNavigation from "./navigation-v3";
import DataHealthV3 from "./data-health-v3";
import {AdvancedAlerts,TabDisclosureGuide} from "./intelligence-v2-panels";
import {AdminUserPanel,applyUserVisibility,UserCustomizationPanel,useUserAccess} from "./user-customization";
import {closeDropdowns,type NavigationTarget} from "./navigation-context";

function AuthRefreshBridge(){const last=useRef("");useEffect(()=>{const read=()=>`${localStorage.getItem("dailyReportUserEmail")||""}|${localStorage.getItem("dailyReportUserToken")||""}`;last.current=read();const id=setInterval(()=>{const next=read();if(next!==last.current){last.current=next;window.dispatchEvent(new Event("daily-report-auth-changed"))}},500);return()=>clearInterval(id)},[]);return null}

const REPLACEMENTS=new Set(["Portfolio","Events","Opportunities","Research","Alerts","Macro","Large Flow"]);

export default function IntelligenceAugmentations(){
 const[baseActive,setBaseActive]=useState(""),[commandActive,setCommandActive]=useState(false),[mainTarget,setMainTarget]=useState<Element|null>(null),[tabTarget,setTabTarget]=useState<Element|null>(null),[navTarget,setNavTarget]=useState<Element|null>(null),[navContext,setNavContext]=useState<(NavigationTarget&{nonce:number})|null>(null);const{data:access,reload}=useUserAccess();
 useEffect(()=>{const sync=()=>{const nav=document.querySelector(".nav");const direct=nav?Array.from(nav.children).find(x=>x.tagName==="BUTTON"&&x.classList.contains("active")):null;if(direct)setBaseActive((direct.textContent||"").trim());setMainTarget(document.querySelector("main.container"));setTabTarget(document.querySelector("main.container > .tab-panel:last-of-type"));setNavTarget(nav)};sync();const observer=new MutationObserver(()=>requestAnimationFrame(sync));observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:["class"]});return()=>observer.disconnect()},[]);
 useEffect(()=>{const handler=(ev:Event)=>{const raw=(ev as CustomEvent).detail;const target:NavigationTarget=typeof raw==="string"?{tab:raw}:raw||{};const name=target.tab;if(!name)return;closeDropdowns();setNavContext({...target,nonce:Date.now()});if(name==="Command Center"){setCommandActive(true);return}setCommandActive(false);if(navTarget){const btn=Array.from(navTarget.children).find(x=>x.tagName==="BUTTON"&&(x.textContent||"").trim()===name) as HTMLButtonElement|undefined;btn?.click()}};window.addEventListener("daily-report-nav-request",handler);return()=>window.removeEventListener("daily-report-nav-request",handler)},[navTarget]);
 useEffect(()=>{closeDropdowns()},[baseActive,commandActive]);
 useEffect(()=>{const handler=(ev:Event)=>{const t=ev.target as HTMLElement|null;if(!t||t.closest("summary"))return;if(t.closest("button,select,[role='tab'],input[type='radio'],input[type='checkbox']"))requestAnimationFrame(closeDropdowns)};document.addEventListener("click",handler,true);document.addEventListener("change",handler,true);return()=>{document.removeEventListener("click",handler,true);document.removeEventListener("change",handler,true)}},[]);
 useEffect(()=>{document.body.classList.toggle("command-center-v3-mode",commandActive);document.body.classList.toggle("workspace-replacement-v3-mode",!commandActive&&REPLACEMENTS.has(baseActive));document.body.dataset.replacementTab=!commandActive&&REPLACEMENTS.has(baseActive)?baseActive:"";return()=>{document.body.classList.remove("command-center-v3-mode","workspace-replacement-v3-mode");delete document.body.dataset.replacementTab}},[baseActive,commandActive]);
 useEffect(()=>{if(access){applyUserVisibility(access);const id=setTimeout(()=>applyUserVisibility(access),100);return()=>clearTimeout(id)}},[access,baseActive,commandActive]);
 const upgraded=mainTarget?(commandActive?createPortal(<CommandCenterPanel/>,mainTarget):baseActive==="Portfolio"?createPortal(<PortfolioWorkspaceV3 navigation={navContext}/>,mainTarget):baseActive==="Events"?createPortal(<EventsWorkspaceV3/>,mainTarget):baseActive==="Opportunities"?createPortal(<OpportunitiesWorkspaceV3 navigation={navContext}/>,mainTarget):baseActive==="Research"?createPortal(<ResearchWorkspaceV3 navigation={navContext}/>,mainTarget):baseActive==="Alerts"?createPortal(<AdvancedAlerts/>,mainTarget):baseActive==="Macro"?createPortal(<MacroWorkspaceV3 navigation={navContext}/>,mainTarget):baseActive==="Large Flow"?createPortal(<LargeFlowWorkspaceV3 navigation={navContext}/>,mainTarget):null):null;
 const nav=navTarget?createPortal(<GroupedNavigation nav={navTarget} active={baseActive} commandActive={commandActive} access={access} onCommand={()=>{closeDropdowns();setCommandActive(true)}}/>,navTarget):null;
 const alertHistory=mainTarget&&!commandActive&&baseActive==="Alerts"?createPortal(<AlertEventPanel/>,mainTarget):null;
 const guideTabs=new Set(["Report","Markets","World News","Regime","Theses"]);const guide=tabTarget&&!commandActive&&guideTabs.has(baseActive)?createPortal(<TabDisclosureGuide active={baseActive}/>,tabTarget):null;
 const settings=tabTarget&&!commandActive&&baseActive==="Settings"&&access?createPortal(<section className="augmentation-settings"><DataHealthV3/><UserCustomizationPanel access={access} onChanged={reload}/>{access.permissions.can_admin_users&&<AdminUserPanel/>}</section>,tabTarget):null;
 return <><AuthRefreshBridge/>{nav}{upgraded}{alertHistory}{guide}{settings}<SecurityDrawer/></>;
}
