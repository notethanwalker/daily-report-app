"use client";
import DeepShell from "../deep-shell";
import PortfolioWorkspaceV3 from "../../../portfolio-workspace-v3";
export default function Page(){return <DeepShell title="Portfolio" layer="Research → Deployment" description="Private positions, risk, history and portfolio management live one level below the decision stack.">{()=> <PortfolioWorkspaceV3/>}</DeepShell>}
