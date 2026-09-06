export type NavigationTarget={tab:string;symbol?:string;subtab?:string;section?:string;filter?:string;portfolioId?:number};

export function navigateTo(target:string|NavigationTarget){
  const detail=typeof target==="string"?{tab:target}:{...target};
  window.dispatchEvent(new CustomEvent("daily-report-nav-request",{detail}));
}

export function closeDropdowns(){
  document.querySelectorAll("details[open]").forEach(el=>el.removeAttribute("open"));
}
