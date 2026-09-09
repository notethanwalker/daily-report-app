import {NextRequest,NextResponse} from "next/server";

export const dynamic="force-dynamic";
const TARGET=(process.env.BACKEND_INTERNAL_URL||"https://daily-report-api-ero2.onrender.com").replace(/\/$/,"");

type Ctx={params:Promise<{path:string[]}>};

async function fetchUpstream(target:URL,init:RequestInit,method:string){
 const attempts=method==="GET"||method==="HEAD"?2:1;
 let lastError:unknown=null;
 for(let i=0;i<attempts;i++){
  try{
   const response=await fetch(target,init);
   if(i+1<attempts&&[502,503,504].includes(response.status))continue;
   return response;
  }catch(error){
   lastError=error;
   if(i+1>=attempts)break;
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
  const upstream=await fetchUpstream(target,{method,headers,body,redirect:"manual",cache:"no-store"},method);
  const responseHeaders=new Headers(upstream.headers);
  responseHeaders.delete("content-encoding");responseHeaders.delete("content-length");responseHeaders.delete("transfer-encoding");
  const getSetCookie=(upstream.headers as Headers&{getSetCookie?:()=>string[]}).getSetCookie;
  if(getSetCookie){responseHeaders.delete("set-cookie");for(const cookie of getSetCookie.call(upstream.headers))responseHeaders.append("set-cookie",cookie)}
  return new NextResponse(await upstream.arrayBuffer(),{status:upstream.status,statusText:upstream.statusText,headers:responseHeaders});
 }catch(error){
  console.error("Backend proxy request failed",error);
  return NextResponse.json({detail:"Backend temporarily unavailable"},{status:502});
 }
}

export const GET=proxy;export const POST=proxy;export const PUT=proxy;export const PATCH=proxy;export const DELETE=proxy;export const OPTIONS=proxy;
