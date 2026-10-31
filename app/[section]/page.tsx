import Workspace from '@/components/workspace';
import { notFound } from 'next/navigation';
import { Suspense } from 'react';
export async function generateStaticParams(){return ['dashboard','import','records','diagnostics','risk-analysis','models','reports','machines','maintenance'].map(section=>({section}));}
export default async function Page({params}:{params:Promise<{section:string}>}){const {section}=await params;if(!['dashboard','import','records','diagnostics','risk-analysis','models','reports','machines','maintenance'].includes(section))notFound();return <Suspense fallback={<div className="workspace-loading">Preparing your workspace…</div>}><Workspace section={section}/></Suspense>;}
