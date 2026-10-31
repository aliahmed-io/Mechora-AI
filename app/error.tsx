'use client';
import Link from 'next/link';
export default function ErrorPage({reset}:{error:Error;reset:()=>void}){
 return <main className="empty-state" style={{minHeight:'100dvh'}}><p className="eyebrow">Mechora AI</p><h2>Let’s bring things back into focus.</h2><p>The page could not finish loading. Try again, or return to the overview to continue your analysis.</p><div className="hero-actions"><button className="button" onClick={reset}>Try again</button><Link href="/dashboard" className="text-link">Return to overview →</Link></div></main>;
}
