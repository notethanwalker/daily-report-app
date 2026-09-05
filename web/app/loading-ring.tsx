export default function LoadingRing({label="Loading"}:{label?:string}){
 return <span className="loading-ring" role="status" aria-label={label}><span/></span>;
}
