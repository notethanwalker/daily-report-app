"use client";

type Release={version:string;date:string;title:string;summary:string;changes:string[]};

const RELEASES:Release[]=[
 {
  version:"v1.4",
  date:"September 5, 2026",
  title:"Reliability, validation, and system visibility",
  summary:"Strengthened ticker handling, market-data failure reporting, desktop layout, backend/API observability, and controlled production releases.",
  changes:[
   "Added exact ticker validation before new symbols can be added to the watchlist.",
   "Added startup watchlist validation and automatic removal only when a ticker is confirmed invalid by the market-data provider.",
   "Added a 24-hour ticker-validation cache to reduce provider usage.",
   "Added persistent per-ticker market-data error rows with specific failure messages, clearer visual treatment, and Retry controls.",
   "Added responsive desktop layouts that use substantially more native screen width while preserving the mobile PWA layout.",
   "Added Settings backend/API monitoring with provider status, route status, HTTP response state, and latency.",
   "Fixed the Settings status monitor TypeScript production-build failure.",
   "Disabled automatic Vercel Git deployments so production releases can be deployed deliberately and conserve free-tier build capacity.",
   "Removed the per-push report smoke workflow so ordinary code commits no longer wait on Render or create report snapshots as a side effect."
  ]
 },
 {
  version:"v1.3",
  date:"September 5, 2026",
  title:"Markets UX and loading/error hardening",
  summary:"Reworked Markets interaction and made network/provider failures explicit throughout the application.",
  changes:[
   "Removed the separate Markets card-view option and made ticker rows expandable in place.",
   "Added watchlist ticker removal controls.",
   "Added startup, tab-loading, provider-loading, timeout, network-error, and retry states.",
   "Added clearer World News, Macro, Report, ticker-search, and watchlist-action errors.",
   "Added directional green/red market metrics while keeping valuation ratios visually neutral.",
   "Expanded market metrics to include 50MA, 100MA, 200MA, provider-history ATH, price vs. ATH, relative volume, P/S, P/E, and PEG."
  ]
 },
 {
  version:"v1.2",
  date:"September 4–5, 2026",
  title:"Macro history and market intelligence",
  summary:"Added historical rotation analysis, macro-event context, richer dashboard intelligence, and durable historical storage.",
  changes:[
   "Added historical daily-bar persistence and backfilled 2026 market history for the supported rotation universe.",
   "Added historical sector/theme rotation scoring, leadership counts, leader/laggard timelines, and stock-vs-benchmark divergence analysis.",
   "Integrated MacroRadar's free macro calendar and attached nearby releases, central-bank events, and trade actions as possible catalysts rather than causal claims.",
   "Added the Midnight Pro dashboard, market sentiment synthesis, themes, and Sector Performance presentation.",
   "Added automated weekday refreshes for watchlist data, macro rotation data, rotating fundamentals, and saved Daily Report snapshots."
  ]
 },
 {
  version:"v1.1",
  date:"August–September 2026",
  title:"Provider architecture and persistent backend",
  summary:"Moved the prototype into a persistent multi-provider backend with validation, news, FX, fundamentals, and report history.",
  changes:[
   "Added FastAPI backend deployment on Render and PostgreSQL persistence for watchlists, market snapshots, historical bars, verification data, fundamentals, reports, and flow-event storage.",
   "Integrated Twelve Data as the primary market-history and market-snapshot provider.",
   "Integrated Alpha Vantage as a quota-controlled secondary verifier and fundamentals provider with a seven-day persistent cache.",
   "Added GDELT World News with a Google News RSS fallback and rate-limit cooldown behavior.",
   "Added Frankfurter/ECB-derived major-currency tracking.",
   "Added source metadata and links throughout externally sourced market/news data.",
   "Added report snapshot history and backend configuration endpoints."
  ]
 },
 {
  version:"v1.0",
  date:"August 19, 2026",
  title:"Daily Report PWA foundation",
  summary:"Established the Mac-free iPhone-installable Daily Report application and the core market-report workflow.",
  changes:[
   "Created the Next.js/React progressive web app for installation from iPhone Safari without requiring a Mac or App Store build pipeline.",
   "Added Report, Markets, World News, Large Flow, Macro, and Settings navigation.",
   "Established the Daily Report watchlist workflow and market-report structure.",
   "Established the provider-to-validation-to-storage-to-analysis architecture so AI analysis does not invent raw market values.",
   "Connected the production frontend to the Render-hosted backend and persistent database."
  ]
 }
];

export default function VersionHistory(){
 return <details className="card" style={{marginTop:16}}>
  <summary style={{cursor:"pointer",fontWeight:700,fontSize:"1.05rem"}}>Version History</summary>
  <p className="muted" style={{marginTop:10}}>Major application releases and development changes, newest first.</p>
  <div style={{display:"grid",gap:12,marginTop:14}}>
   {RELEASES.map(release=><article key={release.version} style={{borderTop:"1px solid #1c2730",paddingTop:14}}>
    <div className="row"><div><strong>{release.version} · {release.title}</strong><p className="muted">{release.date}</p></div></div>
    <p>{release.summary}</p>
    <ul>{release.changes.map(change=><li key={change}>{change}</li>)}</ul>
   </article>)}
  </div>
 </details>;
}
