"use client";
import LoadingRing from "./loading-ring";

export function LoadingState({title,detail,compact=false}:{title:string;detail?:string;compact?:boolean}){
 return <div className={`card loading-state is-loading ${compact?"compact":""}`} role="status" aria-live="polite"><LoadingRing label={title}/><div><strong>{title}</strong>{detail&&<p>{detail}</p>}</div></div>;
}

export function ErrorState({title,detail,onRetry}:{title:string;detail:string;onRetry?:()=>void}){
 return <div className="error-state" role="alert"><div><strong>{title}</strong><p>{detail}</p></div>{onRetry&&<button className="btn" onClick={onRetry}>Retry</button>}</div>;
}
