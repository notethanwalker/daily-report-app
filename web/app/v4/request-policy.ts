export const V4_TIMEOUT_FAST_MS=12_000;
export const V4_TIMEOUT_HEAVY_MS=35_000;

export async function fetchJsonV4(path:string,options:RequestInit={},timeout=V4_TIMEOUT_FAST_MS){
 const controller=new AbortController();
 const timer=setTimeout(()=>controller.abort(),timeout);
 const parentSignal=options.signal;
 const abortFromParent=()=>controller.abort();
 if(parentSignal){
  if(parentSignal.aborted)controller.abort();
  else parentSignal.addEventListener("abort",abortFromParent,{once:true});
 }
 try{
  const response=await fetch(path,{cache:"no-store",credentials:"include",...options,signal:controller.signal});
  const data=await response.json().catch(()=>({}));
  if(!response.ok)throw new Error(data?.detail||`HTTP ${response.status}`);
  return data;
 }catch(error:any){
  if(error?.name==="AbortError")throw new Error("Request timed out. Retry this view.");
  throw error;
 }finally{
  clearTimeout(timer);
  parentSignal?.removeEventListener("abort",abortFromParent);
 }
}
