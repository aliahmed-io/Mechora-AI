'use client';
import type { Explanation } from '@/lib/api';
import { percent } from '@/lib/api';
export default function ProductTypeComparison({values}:{values:Explanation['type_comparison']}){
 if(!values?.length)return null;
 return <section className="workspace-panel"><div className="panel-heading"><div><h2>How does product type affect this estimate?</h2><p>All five numeric measurements stay fixed. Only the L/M/H quality variant changes.</p></div></div><div className="type-comparison">{values.map(v=><div key={v.type} className={v.observed?'observed':''}><span>Type {v.type}{v.observed&&<small>Observed</small>}{!v.seen_in_training&&<small>Not in training</small>}</span><strong>{percent(v.probability)}</strong><div className="type-comparison-bar"><span style={{width:`${v.probability*100}%`}}/></div><small>{v.observed?'Original prediction':`${v.difference>=0?'+':''}${(v.difference*100).toFixed(2)} percentage points`}</small></div>)}</div><p className="form-note">L, M, and H represent product-quality variants in the training schema. Variants absent from the training data are marked and their estimates are unvalidated. This is a model comparison, not a suggestion that changing product type causes or prevents failure.</p></section>;
}
