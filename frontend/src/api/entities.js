import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const rules={
 list:()=>api('/rules'),
 active:()=>api('/rules/active'),
 get:id=>api('/rules/'+id),
 create:data=>api('/rules',{method:'POST',body:JSON.stringify(data)}),
 replays:id=>api('/rules/'+id+'/replays'),
 createReplays:(id,job_ids)=>api('/rules/'+id+'/replays',{method:'POST',body:JSON.stringify({job_ids})}),
 activate:id=>api('/rules/'+id+'/activate',{method:'POST'}),
 rollback:id=>api('/rules/'+id+'/rollback',{method:'POST'}),
};
