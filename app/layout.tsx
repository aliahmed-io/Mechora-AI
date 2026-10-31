import type { Metadata } from 'next';
import './globals.css';
import './workspace.css';
import './operations.css';
import './landing-fixes.css';
export const metadata: Metadata = {title:'Mechora AI — From data to uptime',description:'Predictive maintenance, reimagined. Understand operating conditions, estimate failure risk, and investigate the factors behind predictions.'};
export default function RootLayout({children}:{children:React.ReactNode}) { return <html lang="en"><body>{children}</body></html>; }
