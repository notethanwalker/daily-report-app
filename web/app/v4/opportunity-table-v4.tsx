"use client";

import OpportunityFormulaBuilderV4 from "./opportunity-formula-builder-v4";

export default function OpportunityTableV4({rows,onOpen}:{rows:any[];onOpen:(symbol:string)=>void}){
 void rows;
 return <OpportunityFormulaBuilderV4 onOpen={onOpen}/>;
}
