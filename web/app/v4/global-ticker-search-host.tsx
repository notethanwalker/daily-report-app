"use client";

import {useEffect,useState} from "react";
import GlobalTickerSearchV4 from "./global-ticker-search-v4";

export default function GlobalTickerSearchHost(){
 const[visible,setVisible]=useState(false);
 useEffect(()=>{
  const sync=()=>setVisible(!!document.querySelector(".v4-shell"));
  sync();
  const observer=new MutationObserver(sync);
  observer.observe(document.body,{childList:true,subtree:true});
  return()=>observer.disconnect();
 },[]);
 if(!visible)return null;
 return <aside className="v4-global-search-host" aria-label="Global security navigation"><GlobalTickerSearchV4 compact/></aside>;
}
