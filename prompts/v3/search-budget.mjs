import {appendFileSync,readFileSync} from 'node:fs';
export const name='audit-search-budget';
export const inject=['tools'];
export function createGuard({budgetMs=1140000,now=Date.now,startAt,log=()=>{}}={}) {
 const started=startAt ?? now();
 const denied=()=>({isError:true,content:[{type:'text',text:'SEARCH_BUDGET_EXHAUSTED: External evidence collection has reached 19 minutes from case start. Do not search, fetch, or use shell/code to find more evidence. Finish all frozen claims using evidence already obtained. Mark insufficient factual evidence unresolved; never treat a timeout as contradicted. Use read/write tools to save the complete result JSON now.'}],error:{message:'Search budget exhausted',info:{name:'SearchBudgetError',code:'SEARCH_BUDGET_EXHAUSTED'}}});
 return async (exec,next)=>{
  const web=['web_search','web_fetch'].includes(exec.name);
  const shell=['bash','pwsh','run_code'].includes(exec.name);
  if(!web&&!shell)return next();
  const remaining=budgetMs-(now()-started);
  if(remaining<=0){log({event:'blocked',tool:exec.name,at:now()});return denied();}
  const controller=new AbortController();const upstream=exec.signal;
  exec.signal=upstream?AbortSignal.any([upstream,controller.signal]):controller.signal;
  const timer=setTimeout(()=>controller.abort(new Error('SEARCH_BUDGET_EXHAUSTED')),remaining);
  try {const result=await next();return controller.signal.aborted?denied():result;}
  catch(error){if(controller.signal.aborted)return denied();throw error;}
  finally {clearTimeout(timer);exec.signal=upstream;}
 };
}
export function apply(ctx){
 const startAt=JSON.parse(readFileSync('budget-clock.json','utf8')).started_at_ms;
 appendFileSync('search-budget-events.jsonl',JSON.stringify({event:'budget_loaded',started_at_ms:startAt,deadline_ms:startAt+1140000})+'\n');
 ctx.on('tools/execute',createGuard({startAt,log:event=>appendFileSync('search-budget-events.jsonl',JSON.stringify(event)+'\n')}));
}
