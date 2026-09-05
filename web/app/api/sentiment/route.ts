import {NextResponse} from "next/server";

export const revalidate=900;
const UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36";
const clamp=(v:number)=>Math.max(0,Math.min(100,v));

async function cnn(){
 const r=await fetch("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",{headers:{"User-Agent":UA,Accept:"application/json, text/plain, */*",Origin:"https://www.cnn.com",Referer:"https://www.cnn.com/"},next:{revalidate:900}});if(!r.ok)throw new Error("cnn");const d=await r.json();const f=d?.fear_and_greed;const score=Number(f?.score);if(!Number.isFinite(score))throw new Error("cnn parse");return{id:"cnn",name:"CNN Fear & Greed",score:+score.toFixed(1),label:String(f?.rating||"Neutral").replaceAll("_"," "),detail:`Previous close ${Number(f?.previous_close??score).toFixed(1)}`,as_of:f?.timestamp,source_url:"https://www.cnn.com/markets/fear-and-greed",scale:"0 fear → 100 greed"};
}
function text(html:string){return html.replace(/<script[\s\S]*?<\/script>/gi," ").replace(/<style[\s\S]*?<\/style>/gi," ").replace(/<[^>]+>/g," ").replace(/&nbsp;/g," ").replace(/\s+/g," ");}
async function aaii(){
 const r=await fetch("https://www.aaii.com/sentiment-survey",{headers:{"User-Agent":UA,Accept:"text/html"},next:{revalidate:3600}});if(!r.ok)throw new Error("aaii");const p=text(await r.text());const b=p.match(/Bullish\s+([0-9]+(?:\.[0-9]+)?)%/i),br=p.match(/Bearish\s+([0-9]+(?:\.[0-9]+)?)%/i);if(!b||!br)throw new Error("aaii parse");const bull=+b[1],bear=+br[1],spread=bull-bear,score=clamp(50+spread*1.6);return{id:"aaii",name:"AAII Investor Sentiment",score:+score.toFixed(1),label:spread>=8?"Bullish":spread<=-8?"Bearish":"Mixed",detail:`Bull ${bull.toFixed(1)}% · Bear ${bear.toFixed(1)}% · spread ${spread>=0?"+":""}${spread.toFixed(1)} pp`,source_url:"https://www.aaii.com/sentiment-survey",scale:"Normalized from bull-bear spread"};
}
async function cboe(){
 const r=await fetch("https://www.cboe.com/markets/us/options/market-statistics/daily",{headers:{"User-Agent":UA,Accept:"text/html"},next:{revalidate:1800}});if(!r.ok)throw new Error("cboe");const p=text(await r.text());const m=p.match(/TOTAL PUT\/CALL RATIO\s+([0-9]+(?:\.[0-9]+)?)/i);if(!m)throw new Error("cboe parse");const ratio=+m[1],score=clamp(111.7-66.7*ratio);return{id:"cboe",name:"Cboe Put/Call",score:+score.toFixed(1),label:ratio<.75?"Risk-on":ratio<=1?"Balanced":"Defensive",detail:`Total put/call ratio ${ratio.toFixed(2)}`,source_url:"https://www.cboe.com/markets/us/options/market-statistics/daily",scale:"Normalized; lower put/call = more risk-on"};
}
export async function GET(){const settled=await Promise.allSettled([cnn(),aaii(),cboe()]);const meters=settled.flatMap(x=>x.status==="fulfilled"?[x.value]:[]);const unavailable=["CNN","AAII","Cboe"].filter((_,i)=>settled[i].status==="rejected");return NextResponse.json({meters,unavailable,retrieved_at:new Date().toISOString(),note:"AAII and Cboe are normalized to 0–100 only for visual comparison; raw source values are shown in each card."});}
