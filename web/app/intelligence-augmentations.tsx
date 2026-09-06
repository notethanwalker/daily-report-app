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

function AuthRefreshBridge(){const last=useRef("");useEffect(()=>{const read=()=>`${localStorage.getItem("dailyReportUserEmail")||""}|${localStorage.getItem("dailyReportUserToken")||""}`;last.current=read();const id=setInterval(()=>{const next=read();if(next!==last.current){last.current=next;window.dispatchEvent(new Event("daily-report-auth-changed"))}},500);return()=>clearInterval(id)},[]);return null}

const REPLACEMENTS=new Set(["Portfolio","Events","Opportunities","Research","Alerts","Macro","Large Flow"]);

export default function IntelligenceAugmentations(){
 const[baseActive,setBaseActive]=useState(""),[commandActive,setCommandActive]=useState(false),[mainTarget,setMainTarget]=useState<Element|null>(null),[tabTarget,setTabTarget]=useState<Element|null>(null),[navTarget,setNavTarget]=useState<Element|null>(null);const{data:access,reload}=useUserAccess();
 useEffect(()=>{const sync=()=>{const nav=document.querySelector(".nav");const direct=nav?Array.from(nav.children).find(x=>x.tagName==="BUTTON"&&x.classList.contains("active")):null;if(direct)setBaseActive((direct.textContent||"").trim());setMainTarget(document.querySelector("main.container"));setTabTarget(document.querySelector("main.container > .tab-panel:last-of-type"));setNavTarget(nav)};sync();const observer=new MutationObserver(()=>requestAnimationFrame(sync));observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:["class"]});return()=>observer.disconnect()},[]);
 useEffect(()=>{const handler=(ev:Event)=>{const name=(ev as CustomEvent).detail as string;if(!name)return;if(name==="Command Center"){setCommandActive(true);return}setCommandActive(false);if(navTarget){const btn=Array.from(navTarget.children).find(x=>x.tagName==="BUTTON"&&(x.textContent||"").trim()===name) as HTMLButtonElement|undefined;btn?.click()}};window.addEventListener("daily-report-nav-request",handler);return()=>window.removeEventListener("daily-report-nav-request",handler)},[navTarget]);
 useEffect(()=>{document.body.classList.toggle("command-center-v3-mode",commandActive);document.body.classList.toggle("workspace-replacement-v3-mode",!commandActive&&REPLACEMENTS.has(baseActive));document.body.dataset.replacementTab=!commandActive&&REPLACEMENTS.has(baseActive)?baseActive:"";return()=>{document.body.classList.remove("command-center-v3-mode","workspace-replacement-v3-mode");delete document.body.dataset.replacementTab}},[baseActive,commandActive]);
 useEffect(()=>{if(access){applyUserVisibility(access);const id=setTimeout(()=>applyUserVisibility(access),100);return()=>clearTimeout(id)}},[access,baseActive,commandActive]);
 const active=commandActive?"Command Center":baseActive;
 const upgraded=mainTarget?(commandActive?createPortal(<CommandCenterPanel/>,mainTarget):baseActive==="Portfolio"?createPortal(<PortfolioWorkspaceV3/>,mainTarget):baseActive==="Events"?createPortal(<EventsWorkspaceV3/>,mainTarget):baseActive==="Opportunities"?createPortal(<OpportunitiesWorkspaceV3/>,mainTarget):baseActive==="Research"?createPortal(<ResearchWorkspaceV3/>,mainTarget):baseActive==="Alerts"?createPortal(<AdvancedAlerts/>,mainTarget):baseActive==="Macro"?createPortal(<MacroWorkspaceV3/>,mainTarget):baseActive==="Large Flow"?createPortal(<LargeFlowWorkspaceV3/>,mainTarget):null):null;
 const nav=navTarget?createPortal(<GroupedNavigation nav={navTarget} active={baseActive} commandActive={commandActive} access={access} onCommand={()=>setCommandActive(true)}/>,navTarget):null;
 const alertHistory=mainTarget&&!commandActive&&baseActive==="Alerts"?createPortal(<AlertEventPanel/>,mainTarget):null;
 const guideTabs=new Set(["Report","Markets","World News","Regime","Theses"]);const guide=tabTarget&&!commandActive&&guideTabs.has(baseActive)?createPortal(<TabDisclosureGuide active={baseActive}/>,tabTarget):null;
 const settings=tabTarget&&!commandActive&&baseActive==="Settings"&&access?createPortal(<section className="augmentation-settings"><DataHealthV3/><UserCustomizationPanel access={access} onChanged={reload}/>{access.permissions.can_admin_users&&<AdminUserPanel/>}</section>,tabTarget):null;
 return <><AuthRefreshBridge/>{nav}{upgraded}{alertHistory}{guide}{settings}<SecurityDrawer/></>;
}
