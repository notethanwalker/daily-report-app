"use client";

type Release={version:string;date:string;title:string;summary:string;changes:string[]};

const RELEASES:Release[]=[
 {
  version:"v1.7",
  date:"September 6, 2026",
  title:"Stock intelligence, calendar navigation, and responsive UI",
  summary:"Unified stock-specific intelligence across Opportunities and Research, added a navigable event calendar and richer macro explanations, and hardened the interface across mobile and desktop layouts.",
  changes:[
   "Added a persistent shared per-symbol intelligence cache so Opportunities, Research, catalysts, linked news, flow context, and price history reuse the same hydrated data instead of repeating provider pulls.",
   "Expanded Opportunity cards to hydrate stock-specific unusual-flow matches on demand and fall back to clearly labeled listed-options activity when no unusual-flow observation is available.",
   "Added scheduled catalysts and linked recent news directly to expanded Opportunity views, with explicit per-symbol force refresh controls.",
   "Expanded Research with stored-price visualization and 1M, 3M, 6M, 1Y, and 2Y timeframe controls plus shared flow, catalyst, and linked-news intelligence.",
   "Added a real month-view Events calendar with expandable/selectable days and visual severity states for empty, minor, significant, and tracked-stock significant events.",
   "Restored Macro Possible Reasons beneath rotation bars with linked news, technical-analysis explanations, written summaries, and direct navigation into Leadership detail.",
   "Made macro bars, category entries, and related ticker controls clickable so they route into the corresponding Leadership detail view.",
   "Strengthened responsive behavior across common phone, tablet, and desktop widths with vertical mobile dropdowns, wrapped controls, viewport-safe menus, and self-contained scrolling for dense cards and expanded panels.",
   "Kept automatic Vercel Git deployments disabled so production releases remain manually controlled."
  ]
 },
 {
  version:"v1.6",
  date:"September 5, 2026",
  title:"Macro drilldowns, relative flow, and report intelligence",
  summary:"Expanded macro tracking and explanations, improved relative flow analysis, broadened report intelligence, and refined the professional interaction layer.",
  changes:[
   "Promoted ITA, PAVE, KRE, XBI, IYT, URA, COPX, and XME from suggested macro ETFs into the actively tracked Sector Performance universe and weekday refresh workflow.",
   "Rebuilt Macro Leadership and Weakness as data grids with 1D, 7D, 30D, relative-volume, and clearly labeled rotation-score statistics.",
   "Moved matched news catalysts and technical-analysis explanations directly underneath each ranked macro ticker with ticker-level expansion.",
   "Added nested summary/detail expansion for individual news and technical explanations, including evidence, confidence, source metadata, and source links.",
   "Expanded per-ticker macro catalyst matching and technical reasoning across the full displayed leadership/weakness sets.",
   "Added Large Flow BUY/SELL + CALL/PUT labels with green call-buy/put-sell and red call-sell/put-buy directional heuristics.",
   "Moved Large Flow expiration directly beside strike and added relative Flow/Market-Cap sorting when source market-cap data is available.",
   "Expanded Report sentiment with external market-sentiment meters and increased sortable 1D/7D/30D notable outliers.",
   "Strengthened tab, card, hover, reveal, and click animations while preserving reduced-motion accessibility."
  ]
 },
 {
  version:"v1.5",
  date:"September 5, 2026",
  title:"Flow, currencies, technicals, and interface polish",
  summary:"Restored macro FX context, activated live unusual-options flow, improved valuation retrieval, expanded the rotation universe, and added a more polished interaction system.",
  changes:[
   "Restored world-currency data to both the Report and Macro tabs with current USD cross-rates and 7-day changes.",
   "Activated Large Flow using SquawkFlow's free public unusual-options API with backend caching and explicit non-synthetic fallback behavior.",
   "Changed expanded market rows to retrieve P/E, P/S, and PEG fundamentals on demand and preserve stale cached fundamentals when provider quota is temporarily unavailable.",
   "Moved the ticker-add/search control to the bottom of the Markets tab.",
   "Added a 14-day Williams %R graph across all available provider history to each expanded market row.",
   "Expanded Macro tracking to SPY, QQQ, EUV/Photonics, DRAM/Memory, NCLD/Neocloud, IGV/Software, CIBR/Cybersecurity, ARKX/Space & Defense, NLR/Nuclear, and QTUM/Quantum in addition to the existing sector universe.",
   "Added animated tab transitions, scroll-triggered card reveals, button/click feedback, and reduced-motion accessibility handling.",
   "Updated the weekday refresh workflow to populate the expanded macro universe and warm the live flow cache."
  ]
 },
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
 return <details className="card reveal-card" style={{marginTop:16}}>
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
