"use client";
import DeepShell from "../deep-shell";
import PortfolioWorkspaceV3 from "../../../portfolio-workspace-v3";
import {PortfolioIntelligenceAutoPanel} from "../../../future-release-wrappers";
export default function Page(){return <DeepShell title="Portfolio Intelligence" layer="Research → Deployment" description="Private positions, risk, history, concentration, scenarios and benchmark intelligence live one level below the decision stack.">{()=> <div className="v3-stack"><PortfolioWorkspaceV3/><PortfolioIntelligenceAutoPanel/></div>}</DeepShell>}
