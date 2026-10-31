import Link from 'next/link';
export default function NotFound(){return <main className="empty-state" style={{minHeight:'100dvh'}}><p className="eyebrow">Mechora AI / 404</p><h2>A different direction.</h2><p>This page could not be found. Your saved analyses are available in the workspace.</p><Link href="/dashboard" className="button">Open the workspace →</Link></main>;}
