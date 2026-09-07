"use client";
import {useEffect,useState} from "react";
import {createPortal} from "react-dom";
import {AlertEventPanel,SecurityDrawer} from "./intelligence-extras";
import PortfolioWorkspaceV3 from "./portfolio-workspace-v3";
import EventsWorkspaceV4 from "./events-workspace-v4";
import OpportunitiesWorkspaceV4 from "./opportunities-workspace-v4";
import ResearchWorkspaceV4 from "./research-workspace-v4";
import MacroWorkspaceV4 from "./macro-workspace-v4";
import LargeFlowWorkspaceV3 from "./large-flow-workspace-v3";
import CommandCenterPanel from "./command-center-v3";
import GroupedNavigation from "./navigation-v3";
import DataHealthV3 from "./data-health-v3";
import {AdvancedAlerts,TabDisclosureGuide} from "./intelligence-v2-panels";
import {AdminUserPanel,applyUserVisibility,UserCustomizationPanel,useUserAccess} from "./user-customization";
import {closeDropdowns,type NavigationTarget} from "./navigation-context";

const REPLACEMENTS=new Set(["Portfolio","Events","Opportunities","Research","Alerts","Macro","Large Flow"]);
const VALID=/^[A-Z][A-Z0-9.\-]{0,9}$/;
function inferActiveSymbol(){const a=document.activeElement as HTMLElement|null;if(!a)return undefined;const explicit=a.closest<HTMLElement>("[data-security-symbol]")?.dataset.securitySymbol;if(explicit&&VALID.test(explicit))return explicit;const root=a.closest<HTMLElement>(".portfolio-holding-v3,.opportunity-v3-card,.event-v2-item,.change-row,.flow-grid-table tr,.market-click-row");const text=(root?.querySelector("strong")?.textContent||"").trim().split(/\s|\//)[0].toUpperCase();return VALID.test(text)?text:undefined}
function applyLegacyContext(target:NavigationTarget){if(!target.symbol)return;const s=target.symbol;const run=()=>{if(target.tab==="Markets"){const row=Array.from(document.querySelectorAll<HTMLElement>(".market-click-row")).find(r=>(r.querySelector("strong")?.textContent||"").trim()===s);row?.click();row?.scrollIntoView({block:"center",behavior:"smooth"})}if(target.tab==="Large Flow"){const input=document.querySelector<HTMLInputElement>(".flow-filter-v3 input");if(input){const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value")?.set;setter?.call(input,target.filter||s);input.dispatchEvent(new Event("input",{bubbles:true}));input.dispatchEvent(new Event("change",{bubbles:true}))}}};setTimeout(run,60);setTimeout(run,220)}

export default function IntelligenceAugmentations(){
 const[baseActive,setBaseActive]=useState(""),[commandActive,setCommandActive]=useState(false),[mainTarget,setMainTarget]=useState<Element|null>(null),[tabTarget,setTabTarget]=useState<Element|null>(null),[navTarget,setNavTarget]=useState<Element|null>(null),[navContext,setNavContext]=useState<(NavigationTarget&{nonce:number})|null>(null);const{data:access,reload}=useUserAccess();
 useEffect(()=>{const sync=()=>{const nav=document.querySelector(".nav");const direct=nav?Array.from(nav.children).find(x=>x.tagName==="BUTTON"&&x.classList.contains("active")):null;if(direct)setBaseActive((direct.textContent||"").trim());setMainTarget(document.querySelector("main.container"));setTabTarget(document.querySelector("main.container > .tab-panel:last-of-type"));setNavTarget(nav)};sync();const observer=new MutationObserver(()=>requestAnimationFrame(sync));observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:["class"]});return()=>observer.disconnect()},[]);
 useEffect(()=>{const handler=(ev:Event)=>{const raw=(ev as CustomEvent).detail;let target:NavigationTarget=typeof raw==="string"?{tab:raw}:raw||{};if(!target.symbol){const inferred=inferActiveSymbol();if(inferred)target={...target,symbol:inferred}}if(target.tab==="Large Flow"&&target.symbol&&!target.filter)target={...target,filter:target.symbol,subtab:target.subtab||"Feed"};if(target.tab==="Research"&&target.symbol&&!target.subtab)target={...target,subtab:"Overview"};if(target.tab==="Opportunities"&&target.symbol&&!target.subtab)target={...target,subtab:"Rankings"};const name=target.tab;if(!name)return;closeDropdowns();setNavContext({...target,nonce:Date.now()});if(name==="Command Center"){setCommandActive(true);return}setCommandActive(false);if(navTarget){const btn=Array.from(navTarget.children).find(x=>x.tagName==="BUTTON"&&(x.textContent||"").trim()===name) as HTMLButtonElement|undefined;btn?.click();applyLegacyContext(target)}};window.addEventListener("daily-report-nav-request",handler);return()=>window.removeEventListener("daily-report-nav-request",handler)},[navTarget]);
 useEffect(()=>{closeDropdowns()},[baseActive,commandActive]);
 useEffect(()=>{const handler=(ev:Event)=>{const t=ev.target as HTMLElement|null;if(!t||t.closest("summary"))return;if(t.closest("button,select,[role='tab'],input[type='radio'],input[type='checkbox']"))requestAnimationFrame(closeDropdowns)};document.addEventListener("click",handler,true);document.addEventListener("change",handler,true);return()=>{document.removeEventListener("click",handler,true);document.removeEventListener("change",handler,true)}},[]);
 useEffect(()=>{document.body.classList.toggle("command-center-v3-mode",commandActive);document.body.classList.toggle("workspace-replacement-v3-mode",!commandActive&&REPLACEMENTS.has(baseActive));document.body.dataset.replacementTab=!commandActive&&REPLACEMENTS.has(baseActive)?baseActive:"";return()=>{document.body.classList.remove("command-center-v3-mode","workspace-replacement-v3-mode");delete document.body.dataset.replacementTab}},[baseActive,commandActive]);
 useEffect(()=>{if(access){applyUserVisibility(access);const id=setTimeout(()=>applyUserVisibility(access),100);return()=>clearTimeout(id)}},[access,baseActive,commandActive]);
 const upgraded=mainTarget?(commandActive?createPortal(<CommandCenterPanel/>,mainTarget):baseActive==="Portfolio"?createPortal(<PortfolioWorkspaceV3/>,mainTarget):baseActive==="Events"?createPortal(<EventsWorkspaceV4 navigation={navContext}/>,mainTarget):baseActive==="Opportunities"?createPortal(<OpportunitiesWorkspaceV4 navigation={navContext}/>,mainTarget):baseActive==="Research"?createPortal(<ResearchWorkspaceV4 navigation={navContext}/>,mainTarget):baseActive==="Alerts"?createPortal(<AdvancedAlerts/>,mainTarget):baseActive==="Macro"?createPortal(<MacroWorkspaceV4 navigation={navContext}/>,mainTarget):baseActive==="Large Flow"?createPortal(<LargeFlowWorkspaceV3/>,mainTarget):null):null;
 const nav=navTarget?createPortal(<GroupedNavigation nav={navTarget} active={baseActive} commandActive={commandActive} access={access} onCommand={()=>{closeDropdowns();setCommandActive(true)}}/>,navTarget):null;
 const alertHistory=mainTarget&&!commandActive&&baseActive==="Alerts"?createPortal(<AlertEventPanel/>,mainTarget):null;
 const guideTabs=new Set(["Report","Markets","World News","Regime","Theses"]),guide=tabTarget&&!commandActive&&guideTabs.has(baseActive)?createPortal(<TabDisclosureGuide active={baseActive}/>,tabTarget):null;
 const settings=tabTarget&&!commandActive&&baseActive==="Settings"&&access?createPortal(<section className="augmentation-settings"><DataHealthV3/><UserCustomizationPanel access={access} onChanged={reload}/>{access.permissions.can_admin_users&&<AdminUserPanel/>}</section>,tabTarget):null;
 return <>{nav}{upgraded}{alertHistory}{guide}{settings}<SecurityDrawer/></>;
}
