"use client";

import Link from "next/link";
import {AuthGate,type Account} from "../../auth-shell";

export default function DeepShell({title,layer,description,children}:{title:string;layer:string;description:string;children:(account:Account)=>React.ReactNode}){
 return <AuthGate>{account=><main className="v4-shell deep-v4-shell"><header className="v4-header"><div><span className="v4-kicker">{layer} · EXPANDED DETAIL</span><h1>{title}</h1><p>{description}</p></div><div className="v4-user"><span>{account.name}</span><Link className="source-link" href="/">← Decision Stack</Link></div></header><section className="deep-v4-body">{children(account)}</section></main>}</AuthGate>
}
