"use client";
import {useEffect,useRef,useState} from "react";
import {createPortal} from "react-dom";
import {AlertEventPanel,PortfolioRiskPanel,SecurityDrawer} from "./intelligence-extras";

function AuthRefreshBridge(){
 const last=useRef("");
 useEffect(()=>{const read=()=>`${localStorage.getItem("dailyReportUserEmail")||""}|${localStorage.getItem("dailyReportUserToken")||""}`;last.current=read();const id=setInterval(()=>{const next=read();if(next!==last.current){last.current=next;window.dispatchEvent(new Event("daily-report-auth-changed"))}},500);return()=>clearInterval(id)},[]);
 return null;
}

export default function IntelligenceAugmentations(){
 const[active,setActive]=useState("");const[target,setTarget]=useState<Element|null>(null);
 useEffect(()=>{const sync=()=>{setActive((document.querySelector(".nav button.active")?.textContent||"").trim());setTarget(document.querySelector("main.container > .tab-panel:last-of-type"))};sync();const observer=new MutationObserver(()=>requestAnimationFrame(sync));observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:["class"]});return()=>observer.disconnect()},[]);
 const extra=target&&active==="Portfolio"?createPortal(<PortfolioRiskPanel/>,target):target&&active==="Alerts"?createPortal(<AlertEventPanel/>,target):null;
 return <><AuthRefreshBridge/>{extra}<SecurityDrawer/></>;
}
