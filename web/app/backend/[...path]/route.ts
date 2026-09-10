import {NextRequest,NextResponse} from "next/server";

export const dynamic="force-dynamic";
const TARGET=(process.env.BACKEND_INTERNAL_URL||"https://daily-report-api-ero2.onrender.com").replace(/\/$/,"");
const UPSTREAM_TIMEOUT_MS=60000;

type Ctx={params:Promise<{path:string[]}>};

async function fetchUpstream(target:URL,init:RequestInit,method:string,parentSignal:AbortSignal){
 const attempts=method==="GET"||method==="HEAD"?2:1;
 let lastError:unknown=null;
 for(let i=0;i<attempts;i++){
  if(parentSignal.aborted)throw new DOMException("Client request aborted","AbortError");
  const controller=new AbortController();
  let timedOut=false;
  const abort=()=>controller.abort();
  parentSignal.addEventListener("abort",abort,{once:true});
  const timer=setTimeout(()=>{timedOut=true;controller.abort()},UPSTREAM_TIMEOUT_MS);
  try{
   const response=await fetch(target,{...init,signal:controller.signal});
   if(i+1<attempts&&[502,503,504].includes(response.status))continue;
   return response;
  }catch(error){
   lastError=timedOut?new Error("Backend request timed out"):error;
   if(parentSignal.aborted||i+1>=attempts)break;
  }finally{
   clearTimeout(timer);
   parentSignal.removeEventListener("abort",abort);
  }
 }
 throw lastError instanceof Error?lastError:new Error("Backend request failed");
}

async function proxy(request:NextRequest,ctx:Ctx){
 try{
  const {path}=await ctx.params;
  const suffix=(path||[]).map(encodeURIComponent).join("/");
  const target=new URL(`${TARGET}/${suffix}`);
  request.nextUrl.searchParams.forEach((value,key)=>target.searchParams.append(key,value));
  const headers=new Headers(request.headers);
  headers.delete("host");headers.delete("content-length");headers.delete("x-user-email");headers.delete("x-user-token");headers.delete("x-auth-user-id");
  const method=request.method.toUpperCase();
  const body=method==="GET"||method==="HEAD"?undefined:await request.arrayBuffer();
  const upstream=await fetchUpstream(target,{method,headers,body,redirect:"manual",cache:"no-store"},method,request.signal);
  const responseHeaders=new Headers(upstream.headers);
  responseHeaders.delete("content-encoding");responseHeaders.delete("content-length");responseHeaders.delete("transfer-encoding");
  const getSetCookie=(upstream.headers as Headers&{getSetCookie?:()=>string[]}).getSetCookie;
  if(getSetCookie){responseHeaders.delete("set-cookie");for(const cookie of getSetCookie.call(upstream.headers))responseHeaders.append("set-cookie",cookie)}
  return new NextResponse(await upstream.arrayBuffer(),{status:upstream.status,statusText:upstream.statusText,headers:responseHeaders});
 }catch(error){
  if(error instanceof Error&&error.message==="Backend request timed out")return NextResponse.json({detail:"Backend request timed out"},{status:504});
  console.error("Backend proxy request failed",error);
  return NextResponse.json({detail:"Backend temporarily unavailable"},{status:502});
 }
}

export const GET=proxy;export const POST=proxy;export const PUT=proxy;export const PATCH=proxy;export const DELETE=proxy;export const OPTIONS=proxy;
