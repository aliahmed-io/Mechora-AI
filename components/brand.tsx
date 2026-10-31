import Link from 'next/link';
export function Wordmark(){return <Link href="/" className="wordmark" aria-label="Mechora AI home">MECHORA<span>•</span></Link>;}
export function Dial({value=0,dark=false,label='Mean failure estimate'}:{value?:number,dark?:boolean,label?:string}){
 return <div className={`dial ${dark?'dial-dark':''}`} role="img" aria-label={`${label}: ${value.toFixed(1)} percent`}><svg viewBox="0 0 160 160"><circle className="dial-track" cx="80" cy="80" r="65"/><circle className="dial-value" cx="80" cy="80" r="65" strokeDasharray={`${Math.min(100,value)*4.084} 408.4`} transform="rotate(-90 80 80)"/>{Array.from({length:40},(_,i)=><line key={i} x1="80" y1="5" x2="80" y2={i%5===0?12:9} transform={`rotate(${i*9} 80 80)`}/>)}</svg><div><strong>{value.toFixed(1)}<small>%</small></strong><span>{label}</span></div></div>;
}
