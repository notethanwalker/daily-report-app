"use client";
import {useEffect} from "react";

export default function DestructiveActionGuard(){
 useEffect(()=>{
  const guard=(event:MouseEvent)=>{
   const target=event.target as HTMLElement|null;
   const button=target?.closest?.(".destructive-zone button.danger") as HTMLButtonElement|null;
   if(!button||button.dataset.confirmed==="true")return;
   const label=(button.textContent||"this item").trim();
   if(window.confirm(`${label}? This removes it from your watchlist.`)){
    button.dataset.confirmed="true";
    queueMicrotask(()=>delete button.dataset.confirmed);
    return;
   }
   event.preventDefault();
   event.stopPropagation();
   event.stopImmediatePropagation();
  };
  document.addEventListener("click",guard,true);
  return()=>document.removeEventListener("click",guard,true);
 },[]);
 return null;
}
