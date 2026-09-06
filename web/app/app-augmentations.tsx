"use client";

import {useEffect,useState} from "react";
import {createPortal} from "react-dom";
import PortfolioWorkspace from "./portfolio-workspace";
import {AdminUserPanel,applyUserVisibility,UserCustomizationPanel,useUserAccess} from "./user-customization";

function useActiveTab(){const[active,setActive]=useState("");useEffect(()=>{const read=()=>setActive((document.querySelector(".nav button.active")?.textContent||"").trim());read();const nav=document.querySelector(".nav");if(!nav)return;const observer=new MutationObserver(read);observer.observe(nav,{subtree:true,attributes:true,attributeFilter:["class","style"]});nav.addEventListener("click",read);return()=>{observer.disconnect();nav.removeEventListener("click",read)}},[]);return active}

export default function AppAugmentations(){
 const active=useActiveTab(),{data:access,reload}=useUserAccess(),[target,setTarget]=useState<HTMLElement|null>(null);
 useEffect(()=>{setTarget(document.querySelector("main.container"))},[active]);
 useEffect(()=>{if(access){applyUserVisibility(access);const id=setTimeout(()=>applyUserVisibility(access),80);return()=>clearTimeout(id)}},[access,active]);
 useEffect(()=>{document.body.classList.toggle("portfolio-v2-mode",active==="Portfolio");return()=>document.body.classList.remove("portfolio-v2-mode")},[active]);
 if(!target)return null;
 return <>{active==="Portfolio"&&createPortal(<PortfolioWorkspace/>,target)}{active==="Settings"&&access&&createPortal(<section className="augmentation-settings"><UserCustomizationPanel access={access} onChanged={reload}/>{access.permissions.can_admin_users&&<AdminUserPanel/>}</section>,target)}</>
}
