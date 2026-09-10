"use client";
import {useEffect} from "react";

function apply(root:ParentNode=document){
 root.querySelectorAll<HTMLElement>(".v4-error,.suite-error,.inline-error").forEach(el=>{if(!el.hasAttribute("role"))el.setAttribute("role","alert");if(!el.hasAttribute("aria-live"))el.setAttribute("aria-live","assertive");});
 root.querySelectorAll<HTMLElement>(".v4-loading,.spinner-line,.loading-state").forEach(el=>{if(!el.hasAttribute("role"))el.setAttribute("role","status");if(!el.hasAttribute("aria-live"))el.setAttribute("aria-live","polite");});
 root.querySelectorAll<HTMLButtonElement>("button.active").forEach(el=>{const group=el.closest('[role="radiogroup"],[role="group"]');if(group&&!el.hasAttribute("aria-pressed")&&!el.hasAttribute("aria-checked")&&!el.hasAttribute("aria-current"))el.setAttribute("aria-pressed","true");});
}

export default function AccessibilityRuntime(){
 useEffect(()=>{apply();const observer=new MutationObserver(records=>{for(const record of records)for(const node of Array.from(record.addedNodes))if(node instanceof HTMLElement){apply(node);if(node.matches(".v4-error,.suite-error,.inline-error,.v4-loading,.spinner-line,.loading-state"))apply(node.parentElement||document);}});observer.observe(document.body,{childList:true,subtree:true});return()=>observer.disconnect()},[]);
 return null;
}
