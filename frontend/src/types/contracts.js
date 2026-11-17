/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean,rule_version_id:number|null}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
/** @typedef {{id:number,code:string,name:string,description:string,engine_key:string,config:Object,status:'candidate'|'active'|'retired',is_active:boolean,activated_at:number|null,retired_at:number|null,replay_stats?:Object}} RuleVersion */
/** @typedef {{id:number,rule_version_id:number,job_id:number,status:'pending'|'running'|'completed'|'failed',diff_summary:Object,point_changes:Array<PointChange>,error:string,attempts:number}} ShadowReplay */
/** @typedef {{defect_id:string,mileage_km:number,severity:number,old_group:string,new_group:string,old_role:string,new_role:string,change_type:string}} PointChange */
export {};
