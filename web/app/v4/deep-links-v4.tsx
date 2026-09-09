"use client";
import Link from "next/link";
type Layer="research"|"macro"|"opportunity"|"deployment";
const LINKS:Record<Layer,{href:string;title:string;note:string}[]>={
 research:[{href:"/v4/deep/world-news",title:"World News",note:"Global source-linked context"},{href:"/v4/deep/events",title:"Events",note:"Catalysts and calendars"},{href:"/v4/deep/flow",title:"Large Flow",note:"Unusual options and persistence"},{href:"/v4/deep/portfolio",title:"Portfolio",note:"Positions, risk and history"},{href:"/v4/deep/data-health",title:"Data Health",note:"Lineage and verification"}],
 macro:[{href:"/v4/deep/world-news",title:"World News",note:"Geopolitical and macro context"},{href:"/v4/deep/events",title:"Events",note:"Macro and company catalysts"},{href:"/v4/deep/flow",title:"Large Flow",note:"Cross-check capital behavior"},{href:"/v4/deep/data-health",title:"Data Health",note:"Coverage and source status"}],
 opportunity:[{href:"/v4/deep/flow",title:"Large Flow",note:"Confirmation and unusual activity"},{href:"/v4/deep/world-news",title:"World News",note:"Catalyst context"},{href:"/v4/deep/events",title:"Events",note:"Upcoming risk windows"},{href:"/v4/deep/data-health",title:"Data Health",note:"Scanner coverage and lineage"}],
 deployment:[{href:"/v4/deep/portfolio",title:"Portfolio",note:"Current exposure and risk"},{href:"/v4/deep/events",title:"Events",note:"Deployment timing context"},{href:"/v4/deep/data-health",title:"Data Health",note:"Input quality before allocation"}],
};
export default function DeepLinksV4({layer}:{layer:Layer}){return <details className="v4-card wide deep-links"><summary><div><span className="label">Expandable detail</span><strong>Deep workspaces</strong></div><span>{LINKS[layer].length} tools</span><b>▾</b></summary><div className="deep-link-grid">{LINKS[layer].map(x=><Link href={x.href} key={x.href}><strong>{x.title}</strong><small>{x.note}</small><span>Open →</span></Link>)}</div></details>}
