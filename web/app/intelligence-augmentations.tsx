"use client";
import {useEffect,useRef,useState} from "react";
import {createPortal} from "react-dom";
import {AlertEventPanel,SecurityDrawer} from "./intelligence-extras";
import PortfolioWorkspace from "./portfolio-workspace";
import {AdminUserPanel,applyUserVisibility,UserCustomizationPanel,useUserAccess} from "./user-customization";

function AuthRefreshBridge(){
 const last=useRef("");
 useEffect(()=>{const read=()=>`${localStorage.getItem("dailyReportUserEmail")||""}|${localStorage.getItem("dailyReportUserToken")||""}`;last.current=read();const id=setInterval(()=>{const next=read();if(next!==last.current){last.current=next;window.dispatchEvent(new Event("daily-report-auth-changed"))}},500);return()=>clearInterval(id)},[]);
 return null;
}

export default function IntelligenceAugmentations(){
 const[active,setActive]=useState(""),[mainTarget,setMainTarget]=useState<Element|null>(null),[tabTarget,setTabTarget]=useState<Element|null>(null);const{data:access,reload}=useUserAccess();
 useEffect(()=>{const sync=()=>{setActive((document.querySelector(".nav button.active")?.textContent||"").trim());setMainTarget(document.querySelector("main.container"));setTabTarget(document.querySelector("main.container > .tab-panel:last-of-type"))};sync();const observer=new MutationObserver(()=>requestAnimationFrame(sync));observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:["class"]});return()=>observer.disconnect()},[]);
 useEffect(()=>{document.body.classList.toggle("portfolio-v2-mode",active==="Portfolio");return()=>document.body.classList.remove("portfolio-v2-mode")},[active]);
 useEffect(()=>{if(access){applyUserVisibility(access);const id=setTimeout(()=>applyUserVisibility(access),100);return()=>clearTimeout(id)}},[access,active]);
 const portfolio=mainTarget&&active==="Portfolio"?createPortal(<PortfolioWorkspace/>,mainTarget):null;
 const alerts=tabTarget&&active==="Alerts"?createPortal(<AlertEventPanel/>,tabTarget):null;
 const settings=tabTarget&&active==="Settings"&&access?createPortal(<section className="augmentation-settings"><UserCustomizationPanel access={access} onChanged={reload}/>{access.permissions.can_admin_users&&<AdminUserPanel/>}</section>,tabTarget):null;
 return <><AuthRefreshBridge/>{portfolio}{alerts}{settings}<SecurityDrawer/></>;
}
