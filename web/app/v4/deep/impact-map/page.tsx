"use client";
import DeepShell from "../deep-shell";
import {ImpactMapPanel} from "../../../future-release-panels";
export default function Page(){return <DeepShell title="Catalyst Impact Map" layer="Research → Macro → Portfolio" description="Map recent news and catalysts to tracked tickers, themes and current portfolio exposure with explicit confidence and source links.">{()=> <ImpactMapPanel/>}</DeepShell>}
