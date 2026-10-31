export const features=['Type','Air temperature [K]','Process temperature [K]','Rotational speed [rpm]','Torque [Nm]','Tool wear [min]'] as const;
export type Observation={record_id:string;machine_id?:string;observed_at?:string;source?:string; Type:string; 'Air temperature [K]':number; 'Process temperature [K]':number; 'Rotational speed [rpm]':number; 'Torque [Nm]':number; 'Tool wear [min]':number; probability:number; risk:string};
export type Analysis={id:string;dataset_id:string;dataset_name:string;created_at:string;model_version:string;model_name:string;total:number;high_risk:number;average_probability:number;watch_threshold:number;high_threshold:number};
export type Metric={name?:string;threshold:number;precision:number;recall:number;f1:number;roc_auc:number;pr_auc:number;false_positive_rate:number;brier_score:number;confusion_matrix:number[][]};
export type Model={data_origin?:string;split_audit?:{strategy:string};version:string;trained_at:string;selected_model:string;selection_reason:string;dataset:string;dataset_rows:number;train_rows:number;validation_rows:number;test_rows:number;failure_count:number;threshold:number;watch_threshold:number;comparisons:Metric[];test_metrics:Metric;latency_ms:number;feature_importance:{feature:string;importance:number;std:number}[];curves:Record<string,{x:number;y:number}[]>;threshold_tradeoffs:Metric[];training_distribution:Record<string,{min:number;max:number;median:number;q05:number;q95:number}>};
export type Overview={analysis:Analysis|null;distribution:{name:string;value:number}[];temperature?:{name:string;value:number}[];histogram?:{name:string;value:number}[];by_type?:{name:string;value:number}[];scatter?:{speed:number;torque:number;risk:string}[];records:Observation[];history:Analysis[]};
export type Explanation={type_comparison:{type:string;probability:number;difference:number;observed:boolean;seen_in_training:boolean}[];method:string;description:string;features:{feature:string;value:number;reference_value:number;contribution:number;min:number;max:number;median:number;q05:number;q95:number}[]};
export type Detail=Observation&{explanation:Explanation;model_version:string;predicted_at:string;watch_threshold:number;high_threshold:number};
export type Dataset={id:string;name:string;created_at:string;row_count:number;missing_values:number;ignored_columns:string[];duplicate_rows:number;has_machine_context?:boolean;preview:Record<string,string|number>[]};
export async function api<T>(path:string,options?:RequestInit):Promise<T>{
 let response:Response;
 try{response=await fetch(`/api${path}`,{...options,cache:'no-store',signal:options?.signal||AbortSignal.timeout(60000)});}catch(error){
  if(options?.signal?.aborted)throw error;
  throw new Error(error instanceof DOMException&&error.name==='TimeoutError'?'The operation took too long. Please try again.':'Cannot reach the analysis service. Check that the backend is running, then try again.');
 }
 if(!response.ok){let message=response.status>=500?'The analysis service is unavailable. Check that the backend is running, then try again.':'The request could not be completed.';try{const body=await response.json();message=typeof body.detail==='string'?body.detail:body.detail?.map((e:{msg:string})=>e.msg).join('; ')||message;}catch{}throw new Error(message);}return response.json();
}
export function post<T>(path:string,body:unknown){return api<T>(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
export const percent=(v:number)=>`${(v*100).toFixed(1)}%`;
export const date=(v:string)=>new Date(v).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
