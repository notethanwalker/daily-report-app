"use client";
import DeepShell from "../deep-shell";
import {DashboardLayoutsPanel,ReportComparePanel} from "../../../future-release-panels";
import {OpportunityChangeDigest} from "../../../future-release-wrappers";
export default function Page(){return <DeepShell title="Workspace Tools" layer="Personalization → History → Export" description="Saved dashboard layouts, Opportunity score-change history, report comparison and CSV/JSON/PDF export controls.">{()=> <div className="v3-stack"><DashboardLayoutsPanel/><OpportunityChangeDigest/><ReportComparePanel/></div>}</DeepShell>}
