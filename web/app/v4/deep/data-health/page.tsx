"use client";
import DeepShell from "../deep-shell";
import DataHealthV3 from "../../../data-health-v3";
export default function Page(){return <DeepShell title="Data Health & Lineage" layer="Transparency" description="Connection, freshness, completeness, verification, sources, API budget and queue state are inspected separately.">{()=> <DataHealthV3/>}</DeepShell>}
