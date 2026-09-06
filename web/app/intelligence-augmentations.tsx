"use client";
import {useEffect,useRef} from "react";
import {AlertEventPanel,PortfolioRiskPanel,SecurityDrawer} from "./intelligence-extras";

function AuthRefreshBridge(){
 const last=useRef("");
 useEffect(()=>{const read=()=>`${localStorage.getItem("dailyReportUserEmail")||""}|${localStorage.getItem("dailyReportUserToken")||""}`;last.current=read();const id=setInterval(()=>{const next=read();if(next!==last.current){last.current=next;window.dispatchEvent(new Event("daily-report-auth-changed"))}},500);return()=>clearInterval(id)},[]);
 return null;
}

export default function IntelligenceAugmentations({active}:{active:string}){
 return <><AuthRefreshBridge/>{active==="Portfolio"&&<PortfolioRiskPanel/>}{active==="Alerts"&&<AlertEventPanel/>}<SecurityDrawer/></>;
}
