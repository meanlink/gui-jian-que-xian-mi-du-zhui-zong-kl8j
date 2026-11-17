import {rules,jobs} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {esc,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {RuleStatus,ReplayStatus,ChangeType} from '../constants/enums.js';

const isAdmin=()=>session.user.role==='admin';
const canWrite=()=>session.user.role!=='viewer';

export async function rulePage(){
 const [versionList,allJobs]=await Promise.all([rules.list(),jobs.list()]);
 workspace.ruleVersions=versionList;
 const completedJobs=allJobs.filter(j=>j.status==='completed');
 const active=versionList.find(v=>v.is_active);
 const cards=versionList.map(v=>{
  const s=v.replay_stats||{completed:0,pending:0,failed:0};
  return '<article class="rule-card '+(v.is_active?'is-active':'')+'">'
   +'<div class="rule-card-head"><div><span class="rule-code">'+esc(v.code)+'</span><span class="status-badge '+esc(v.status)+'">'+esc(RuleStatus[v.status]||v.status)+'</span></div>'
   +'<strong>'+esc(v.name)+'</strong><p class="rule-desc">'+esc(v.description||'—')+'</p></div>'
   +'<dl class="rule-meta"><div><dt>计算口径</dt><dd>'+esc(engineLabel(v.engine_key))+'</dd></div>'
   +'<div><dt>口径参数</dt><dd>'+esc(formatConfig(v))+'</dd></div>'
   +'<div><dt>影子回放</dt><dd>完成 '+s.completed+' · 待处理 '+s.pending+' · 失败 '+s.failed+'</dd></div>'
   +'<div><dt>版本时间</dt><dd>'+(v.activated_at?('生效 '+date(v.activated_at)):('创建 '+date(v.created_at)))+'</dd></div></dl>'
   +'<div class="rule-actions"><button class="button small" data-detail="'+v.id+'">查看回放与差异 ↗</button>'
   +(v.status==='candidate'&&isAdmin()?'<button class="button small primary" data-activate="'+v.id+'" '+(s.completed?'':'disabled')+'>确认差异并切换生效</button>':'')
   +(v.status!=='active'&&isAdmin()?'<button class="button small" data-rollback="'+v.id+'">回退到此版本</button>':'')
   +(v.status==='candidate'&&canWrite()?'<button class="button small" data-replay-open="'+v.id+'">追加影子回放</button>':'')
   +(v.status==='active'?'<span class="hint" style="margin:0">当前生效：新建试验按此版本固定</span>':'')+'</div></article>';
 }).join('');

 return heading('06 / RULE VERSIONS','计算规则版本与影子回放',
   '规则升级先做影子回放，固定输入与参数逐点比较分组变化；负责人确认差异后切换。试验在创建时固定版本，排队、恢复与回退都不会让历史试验换版。',
   '<button class="button" id="refresh-rules">刷新版本 ↻</button>')
 +'<section class="panel"><div class="section-title"><h2>版本列表</h2><span>当前生效：'+esc(active?active.code+' · '+active.name:'无')+'</span></div>'
 +'<div class="rule-grid">'+cards+'</div></section>'
 +(canWrite()?'<section class="panel"><div class="section-title"><h2>创建候选规则版本</h2><span>候选版不会影响任何在途试验与简报</span></div>'
 +'<form id="rule-form" class="rule-form"><div class="parameter-grid">'
 +'<label>版本编号<input name="code" required minlength="2" maxlength="40" pattern="[A-Za-z0-9._-]+" placeholder="例如 v2-sev4"></label>'
 +'<label>版本名称<input name="name" required minlength="2" maxlength="160" value="核心点等级约束候选"></label>'
 +'<label>计算口径<select name="engine_key" id="engine-select"><option value="severity_core_1d_dbscan">核心点等级约束口径（候选）</option></select></label>'
 +'<label>核心点最低复核等级<input type="number" name="core_min_severity" min="2" max="5" step="1" value="4" required></label></div>'
 +'<label>版本说明<textarea name="description" rows="2" maxlength="1000" placeholder="说明本次口径调整的业务原因"></textarea></label>'
 +'<label>选择已完成试验做影子回放（可多选，固定输入与参数）<select name="job_ids" id="job-select" multiple size="5">'+completedJobs.map(j=>'<option value="'+j.id+'">'+esc(j.name)+' · '+esc(j.result?.rule?.code||'v1')+' · '+j.params.eps_m+'m/'+j.params.min_points+'点</option>').join('')+'</select></label>'
 +(completedJobs.length?'':'<p class="warning">暂无可回放的已完成试验，可先创建空候选，稍后再追加回放。</p>')
 +'<button type="submit" class="primary">创建候选并发起回放 ↗</button><p class="hint">影子结果只用于差异比对，不进入批准流程与定时简报。核心点最低等级仅限制核心点，低等级点仍可作为边界点归入缺陷带。</p></form></section>':'')
 +'<section class="panel" id="replay-panel" hidden><div class="section-title"><h2 id="replay-title">影子回放与逐点差异</h2><span>差异不影响批准与简报</span></div><div id="replay-body"></div></section>';
}

function engineLabel(key){
 return key==='severity_core_1d_dbscan'?'核心点等级约束一维DBSCAN':key==='baseline_1d_dbscan'?'基础一维DBSCAN':key;
}
function formatConfig(v){
 if(v.engine_key==='severity_core_1d_dbscan')return '核心点最低等级 '+(v.config?.core_min_severity??4)+' 级';
 return '无额外参数';
}

export function bindRules(refresh){
 document.querySelector('#refresh-rules').onclick=refresh;
 const form=document.querySelector('#rule-form');
 if(form)submit(form,async f=>{
  const job_ids=Array.from(f.querySelectorAll('#job-select option:checked')).map(o=>Number(o.value));
  const created=await rules.create({code:f.get('code'),name:f.get('name'),description:f.get('description')||'',engine_key:f.get('engine_key'),config:{core_min_severity:Number(f.get('core_min_severity'))},job_ids});
  notify('候选版本已创建，影子回放已加入后台队列');
  await openDetail(created.id,refresh);
  await refresh();
 });
 document.querySelectorAll('[data-detail]').forEach(b=>b.onclick=()=>openDetail(b.dataset.detail,refresh));
 document.querySelectorAll('[data-replay-open]').forEach(b=>b.onclick=()=>openReplayForm(b.dataset.replayOpen,refresh));
 document.querySelectorAll('[data-activate]').forEach(b=>b.onclick=async()=>{
  if(!confirm('确认已核对逐点差异？切换后新建试验将使用该候选版本，排队中的试验仍保持原版本。'))return;
  try{await rules.activate(b.dataset.activate);notify('规则版本已切换生效');await refresh();}catch(e){notify(e.message,true);}
 });
 document.querySelectorAll('[data-rollback]').forEach(b=>b.onclick=async()=>{
  if(!confirm('回退后新建试验改用该版本；历史试验与简报仍按各自固定版本复现，是否继续？'))return;
  try{await rules.rollback(b.dataset.rollback);notify('已回退规则版本');await refresh();}catch(e){notify(e.message,true);}
 });
}

async function openReplayForm(ruleId,refresh){
 const allJobs=await jobs.list();
 const rule=await rules.get(ruleId);
 const existing=new Set(rule.replays.map(r=>r.job_id));
 const candidates=allJobs.filter(j=>j.status==='completed'&&!existing.has(j.id));
 const panel=document.querySelector('#replay-panel');
 panel.hidden=false;panel.scrollIntoView({behavior:'smooth'});
 document.querySelector('#replay-title').textContent='追加影子回放 · '+rule.code;
 document.querySelector('#replay-body').innerHTML='<form id="add-replay-form"><label>选择已完成试验<select name="job_ids" multiple size="6">'+(candidates.length?candidates.map(j=>'<option value="'+j.id+'">'+esc(j.name)+'</option>').join(''):'<option disabled>没有可追加的已完成试验（均已回放）</option>')+'</select></label><button type="submit" class="primary" '+(candidates.length?'':'disabled')+'>发起回放 ↗</button></form>';
 const f=document.querySelector('#add-replay-form');
 if(f)submit(f,async ff=>{
  const ids=Array.from(ff.querySelectorAll('option:checked')).map(o=>Number(o.value));
  if(!ids.length)throw new Error('请至少选择一个试验');
  await rules.createReplays(ruleId,ids);notify('回放已加入后台队列，稍后刷新查看');await refresh();openDetail(ruleId,refresh);
 });
}

async function openDetail(ruleId,refresh){
 const rule=await rules.get(ruleId);
 const panel=document.querySelector('#replay-panel');
 panel.hidden=false;panel.scrollIntoView({behavior:'smooth'});
 document.querySelector('#replay-title').textContent='影子回放与逐点差异 · '+rule.code;
 const body=document.querySelector('#replay-body');
 if(!rule.replays.length){body.innerHTML='<div class="empty">该版本尚无影子回放。</div>';return;}
 body.innerHTML=rule.replays.map((r,idx)=>replayBlock(rule,r,idx)).join('');
 body.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>applyFilter(Number(b.dataset.rule),Number(b.dataset.idx),b.dataset.filter));
}

function replayBlock(rule,r,idx){
 const sum=r.diff_summary||{};
 const head='<div class="replay-block"><div class="replay-head"><strong>试验 #'+r.job_id+'</strong><span class="status-badge '+esc(r.status)+'">'+esc(ReplayStatus[r.status]||r.status)+'</span><span class="hint">尝试 '+r.attempts+' 次 · '+(r.finished_at?date(r.finished_at):'未完成')+'</span></div>';
 if(r.status==='failed')return head+'<p class="warning">回放失败，已保留旧版结果，生效版本不变。原因：'+esc(r.error||'未知错误')+'</p></div>';
 if(r.status!=='completed')return head+'<p class="hint">回放正在后台进行，完成后刷新查看差异。</p></div>';
 const stats=[['总分组数变化点',sum.group_changed],['新变为噪声',sum.became_noise],['噪声重新入带',sum.left_noise],['核心→边界',sum.core_to_border],['边界→核心',sum.border_to_core],['无变化点',sum.group_unchanged]];
 const cols=[{key:'defect_id',label:'缺陷编号'},{key:'mileage_km',label:'里程km'},{key:'severity',label:'等级'},{key:'old_group',label:'旧分组'},{key:'new_group',label:'候选分组'},{key:'old_role',label:'旧角色'},{key:'new_role',label:'新角色'},{key:'change_type',label:'变化类型'}];
 const rows=(r.point_changes||[]).map(p=>({...p,change_type:ChangeType[p.change_type]||p.change_type}));
 return head
  +'<div class="diff-summary">'+stats.map(([k,v])=>'<div><span>'+k+'</span><strong>'+esc(v??'—')+'</strong></div>').join('')+'</div>'
  +'<p class="hint">固定输入校验和：'+esc(sum.input_checksum||'')+'<br>固定参数：'+esc(JSON.stringify(sum.params||{}))+' · 候选版本：'+esc(sum.rule_code||rule.code)+'</p>'
  +'<div class="diff-filters"><button class="button small" data-filter="all" data-rule="'+rule.id+'" data-idx="'+idx+'">全部</button>'
  +'<button class="button small" data-filter="changed" data-rule="'+rule.id+'" data-idx="'+idx+'">仅看变化</button>'
  +'<button class="button small" data-filter="noise" data-rule="'+rule.id+'" data-idx="'+idx+'">仅看噪声变化</button></div>'
  +'<div id="diff-table-'+rule.id+'-'+idx+'">'+table(cols,rows,'暂无逐点数据。')+'</div></div>';
}

function applyFilter(ruleId,idx,filter){
 rules.get(ruleId).then(rule=>{
  const r=rule.replays[idx];if(!r||r.status!=='completed')return;
  let points=r.point_changes||[];
  if(filter==='changed')points=points.filter(p=>p.change_type!=='unchanged');
  if(filter==='noise')points=points.filter(p=>p.old_group==='孤立/稀疏点'||p.new_group==='孤立/稀疏点');
  const cols=[{key:'defect_id',label:'缺陷编号'},{key:'mileage_km',label:'里程km'},{key:'severity',label:'等级'},{key:'old_group',label:'旧分组'},{key:'new_group',label:'候选分组'},{key:'old_role',label:'旧角色'},{key:'new_role',label:'新角色'},{key:'change_type',label:'变化类型'}];
  const rows=points.map(p=>({...p,change_type:ChangeType[p.change_type]||p.change_type}));
  document.querySelector('#diff-table-'+ruleId+'-'+idx).innerHTML=table(cols,rows,'该筛选条件下没有点。');
 });
}
