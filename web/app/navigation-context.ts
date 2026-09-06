export type NavigationTarget={tab:string;symbol?:string;subtab?:string;section?:string;filter?:string;portfolioId?:number};

export function closeDropdowns(){
  document.querySelectorAll("details[open]").forEach(el=>el.removeAttribute("open"));
}

export function navigateTo(target:string|NavigationTarget){
  // Cross-tab navigation is a state transition. Collapse all transient disclosure
  // UI before changing context so menus/cards from the previous view never remain
  // visually open over the destination.
  closeDropdowns();
  const detail=typeof target==="string"?{tab:target}:{...target};
  window.dispatchEvent(new CustomEvent("daily-report-nav-request",{detail}));
}
