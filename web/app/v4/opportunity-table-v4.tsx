"use client";

import {useState} from "react";
import OpportunityFormulaBuilderV4,{type ActiveOpportunityFormula} from "./opportunity-formula-builder-v4";
import OpportunityCandidateFunnelV4 from "./opportunity-candidate-funnel-v4";
import "./opportunity-formula-v4.css";
import "./opportunity-candidate-funnel-v4.css";

export default function OpportunityTableV4({rows,onOpen}:{rows:any[];onOpen:(symbol:string)=>void}){
 void rows;
 const[formula,setFormula]=useState<ActiveOpportunityFormula|null>(null);
 return <>
  <OpportunityFormulaBuilderV4 onOpen={onOpen} onFormulaState={setFormula}/>
  <OpportunityCandidateFunnelV4 onOpen={onOpen} formula={formula}/>
 </>;
}
