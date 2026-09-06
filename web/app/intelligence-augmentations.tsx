"use client";
import {useEffect,useRef,useState} from "react";
import {createPortal} from "react-dom";
import {AlertEventPanel,SecurityDrawer} from "./intelligence-extras";
import PortfolioWorkspace from "./portfolio-workspace-v2";
import {AdvancedAlerts,AdvancedEvents,AdvancedOpportunities,AdvancedResearch,MacroExpansionSuggestions,TabDisclosureGuide} from "./intelligence-v2-panels";
import {AdminUserPanel,applyUserVisibility,UserCustomizationPanel,useUserAccess} from "./user-customization";

function AuthRefreshBridge(){
 const last=useRef("");
 useEffect(()=>{const read=()=>`${localStorage.getItem("dailyReportUserEmail")||""}|${localStorage.getItem("dailyReportUserToken")||""}`;last.current=read();const id=setInterval(()=>{const next=read();if(next!==last.current){last.current=next;window.dispatchEvent(new Event("daily-report-auth-changed"))}},500);return()=>clearInterval(id)},[]);
 return null;
}

const V2_MODES:Record<string,string>={Portfolio:"portfolio-v2-mode",Events:"events-v2-mode",Opportunities:"opportunities-v2-mode",Research:"research-v2-mode",Alerts:"alerts-v2-mode"};

export default function IntelligenceAugmentations(){
 const[active,setActive]=useState(""),[mainTarget,setMainTarget]=useState<Element|null>(null),[tabTarget,setTabTarget]=useState<Element|null>(null);const{data:access,reload}=useUserAccess();
 useEffect(()=>{const sync=()=>{setActive((document.querySelector(".nav button.active")?.textContent||"").trim());setMainTarget(document.querySelector("main.container"));setTabTarget(document.querySelector("main.container > .tab-panel:last-of-type"))};sync();const observer=new MutationObserver(()=>requestAnimationFrame(sync));observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:["class"]});return()=>observer.disconnect()},[]);
 useEffect(()=>{for(const cls of Object.values(V2_MODES))document.body.classList.toggle(cls,V2_MODES[active]===cls);return()=>{for(const cls of Object.values(V2_MODES))document.body.classList.remove(cls)}},[active]);
 useEffect(()=>{if(access){applyUserVisibility(access);const id=setTimeout(()=>applyUserVisibility(access),100);return()=>clearTimeout(id)}},[access,active]);
 const upgraded=mainTarget?active==="Portfolio"?createPortal(<PortfolioWorkspace/>,mainTarget):active==="Events"?createPortal(<AdvancedEvents/>,mainTarget):active==="Opportunities"?createPortal(<AdvancedOpportunities/>,mainTarget):active==="Research"?createPortal(<AdvancedResearch/>,mainTarget):active==="Alerts"?createPortal(<AdvancedAlerts/>,mainTarget):null:null;
 const alertHistory=mainTarget&&active==="Alerts"?createPortal(<AlertEventPanel/>,mainTarget):null;
 const macroSuggestions=tabTarget&&active==="Macro"?createPortal(<MacroExpansionSuggestions/>,tabTarget):null;
 const guideTabs=new Set(["Report","Markets","World News","Large Flow","Macro","Regime","Theses","Settings"]);const guide=tabTarget&&guideTabs.has(active)?createPortal(<TabDisclosureGuide active={active}/>,tabTarget):null;
 const settings=tabTarget&&active==="Settings"&&access?createPortal(<section className="augmentation-settings"><UserCustomizationPanel access={access} onChanged={reload}/>{access.permissions.can_admin_users&&<AdminUserPanel/>}</section>,tabTarget):null;
 return <><AuthRefreshBridge/>{upgraded}{alertHistory}{macroSuggestions}{guide}{settings}<SecurityDrawer/></>;
}
