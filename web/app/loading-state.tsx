"use client";

export function LoadingState({title,detail,compact=false}:{title:string;detail?:string;compact?:boolean}){
 return <div className={`loading-state ${compact?"compact":""}`} role="status" aria-live="polite"><div className="loading-spinner"/><div><strong>{title}</strong>{detail&&<p>{detail}</p>}</div></div>;
}

export function ErrorState({title,detail,onRetry}:{title:string;detail:string;onRetry?:()=>void}){
 return <div className="error-state" role="alert"><div><strong>{title}</strong><p>{detail}</p></div>{onRetry&&<button className="btn" onClick={onRetry}>Retry</button>}</div>;
}
