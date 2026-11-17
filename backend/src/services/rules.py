"""规则版本与影子回放服务。

关键约定：
- 试验在创建时固定 rule_version_id；排队、worker 恢复、版本切换都不改版。
- 影子回放只写 shadow_replays，不触碰 job 的批准状态、结果与简报。
- 同一时刻至多一个生效版本，由部分唯一索引兜底；并发切换先提交者获胜。
"""
import time
from fastapi import HTTPException
from redis import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.config.settings import REDIS_URL
from src.models import RuleVersion, ShadowReplay, Job, Dataset
from src.services import clustering
from src.services.business import analyze
from src.utils.serialization import checksum


def snapshot(rule):
    """worker 计算时使用的固定口径快照。"""
    return {"id": rule.id, "code": rule.code, "engine_key": rule.engine_key, "config": rule.config or {}}


def active_rule(db):
    return db.scalar(select(RuleVersion).where(RuleVersion.is_active == True))  # noqa: E712


def get_rule(db, rule_id):
    rule = db.get(RuleVersion, rule_id)
    if not rule:
        raise HTTPException(404, '规则版本不存在')
    return rule


def create_candidate(db, data, user):
    if db.scalar(select(RuleVersion).where(RuleVersion.code == data.code)):
        raise HTTPException(422, '规则版本编号已存在')
    if data.engine_key not in clustering.ENGINES:
        raise HTTPException(422, '未知计算口径，无法创建规则版本')
    try:
        config = clustering.validate_config(data.engine_key, data.config)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    rule = RuleVersion(
        code=data.code, name=data.name, description=data.description or '',
        engine_key=data.engine_key, config=config, status='candidate', is_active=False,
        created_by=user.id, created_at=time.time(),
    )
    db.add(rule)
    db.flush()
    if data.job_ids:
        _create_replays(db, rule, data.job_ids, user)
    return rule


def _create_replays(db, rule, job_ids, user):
    if rule.status != 'candidate':
        raise HTTPException(409, '只有候选版本可以发起影子回放')
    replay_ids = []
    for job_id in dict.fromkeys(int(i) for i in job_ids):  # 去重，保序
        job = db.get(Job, job_id)
        if not job:
            raise HTTPException(404, f'分析任务 {job_id} 不存在')
        if job.status != 'completed':
            raise HTTPException(409, f'任务 {job_id} 尚未完成，不能回放')
        exists = db.scalar(select(ShadowReplay).where(
            ShadowReplay.rule_version_id == rule.id, ShadowReplay.job_id == job_id))
        if exists:
            # 已完成项不重复生成；失败/中断项允许继续重试原记录。
            replay_ids.append(exists.id)
            continue
        replay = ShadowReplay(
            rule_version_id=rule.id, job_id=job_id, status='pending',
            created_by=user.id, created_at=time.time(), attempts=0,
        )
        db.add(replay)
        db.flush()
        replay_ids.append(replay.id)
    return replay_ids


def create_replays(db, rule, job_ids, user):
    return _create_replays(db, rule, job_ids, user)


def enqueue_replays(replay_ids):
    if not replay_ids:
        return
    try:
        r = Redis.from_url(REDIS_URL)
        r.rpush('replay:queue', *[str(i) for i in replay_ids])
        r.close()
    except Exception:
        pass  # SQL pending 状态是持久兜底


def _old_points(job):
    """历史结果可能没有逐点快照；缺失时返回空映射，差异里如实标注。"""
    stored = (job.result or {}).get('point_assignments')
    return {str(p['defect_id']): p for p in stored} if stored else {}


def _build_diff(job, candidate_result):
    old_points = _old_points(job)
    new_points = candidate_result.get('point_assignments', [])
    changes = []
    counts = {'total_points': len(new_points), 'group_changed': 0, 'group_unchanged': 0,
              'became_noise': 0, 'left_noise': 0, 'core_to_border': 0, 'border_to_core': 0}
    for new_p in new_points:
        key = str(new_p['defect_id'])
        old_p = old_points.get(key)
        old_group = old_p['group'] if old_p else '（旧结果无逐点快照）'
        old_role = old_p['point_role'] if old_p else '—'
        change_type = 'unchanged'
        if not old_p or old_group != new_p['group']:
            change_type = 'group_changed'
            counts['group_changed'] += 1
            if new_p['group'] == '孤立/稀疏点':
                counts['became_noise'] += 1
            if old_p and old_group == '孤立/稀疏点':
                counts['left_noise'] += 1
        else:
            counts['group_unchanged'] += 1
        if old_p:
            if old_p['is_core'] and not new_p['is_core'] and new_p['group'] != '孤立/稀疏点':
                counts['core_to_border'] += 1
                if change_type == 'unchanged':
                    change_type = 'core_to_border'
            if (not old_p['is_core']) and new_p['is_core']:
                counts['border_to_core'] += 1
                if change_type == 'unchanged':
                    change_type = 'border_to_core'
        changes.append({
            'defect_id': key,
            'mileage_km': new_p['mileage_km'],
            'severity': new_p['severity'],
            'old_group': old_group,
            'new_group': new_p['group'],
            'old_role': old_role,
            'new_role': new_p['point_role'],
            'change_type': change_type,
        })
    summary = {
        'group_changed': counts['group_changed'],
        'group_unchanged': counts['group_unchanged'],
        'became_noise': counts['became_noise'],
        'left_noise': counts['left_noise'],
        'core_to_border': counts['core_to_border'],
        'border_to_core': counts['border_to_core'],
        'changed': counts['group_changed'] + counts['core_to_border'] + counts['border_to_core'],
    }
    return summary, changes, counts


def run_replay(replay_id):
    """worker 调用：幂等。已完成的回放直接返回，失败保留旧版（不影响生效版本）。"""
    from src.config.database import Session
    with Session() as db:
        r = db.get(ShadowReplay, replay_id)
        if not r or r.status != 'pending':
            return  # 已完成/进行中的不重复生成
        r.status = 'running'
        r.attempts = (r.attempts or 0) + 1
        db.commit()
        try:
            job = db.get(Job, r.job_id)
            rule = db.get(RuleVersion, r.rule_version_id)
            dataset = db.get(Dataset, job.dataset_id)
            # 固定输入与参数：直接读取试验创建时的数据批次快照与参数。
            candidate_result = analyze(dataset.records, job.params, snapshot(rule))
            import json as _json
            _json.dumps(candidate_result, allow_nan=False)
            summary, changes, _ = _build_diff(job, candidate_result)
            summary['input_checksum'] = checksum(dataset.records)
            summary['params'] = dict(job.params)
            summary['rule_code'] = rule.code
            r.candidate_result = candidate_result
            r.point_changes = changes
            r.diff_summary = summary
            r.status = 'completed'
            r.error = ''
            r.finished_at = time.time()
            from src.services.audit import record
            record(db, 'worker', 'replay.completed', {'id': r.id, 'rule': rule.code, 'job': job.id, 'changed': summary['changed']})
        except Exception as exc:  # 失败保留旧版：生效版本不变，回放记录失败原因
            r.status = 'failed'
            r.error = str(exc)[:990]
            r.finished_at = time.time()
            from src.services.audit import record
            record(db, 'worker', 'replay.failed', {'id': r.id, 'error': r.error})
        db.commit()


def activate(db, rule, user):
    if rule.status != 'candidate':
        raise HTTPException(409, '只有候选版本在负责人确认差异后可以切换生效')
    done = db.scalar(select(ShadowReplay).where(
        ShadowReplay.rule_version_id == rule.id, ShadowReplay.status == 'completed'))
    if not done:
        raise HTTPException(409, '请先对已完成试验完成至少一次影子回放并确认差异，再切换生效')
    current = active_rule(db)
    now = time.time()
    if current is not None:
        # 先落库退役旧版本并 flush，避免部分唯一索引在同事务中间态触发冲突。
        current.is_active = False
        current.status = 'retired'
        current.retired_at = now
        db.flush()
    rule.is_active = True
    rule.status = 'active'
    rule.activated_at = now
    try:
        db.commit()  # 并发切换时部分唯一索引让后提交者失败，即先完成者确定版本
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, '已有其他版本先完成切换，请刷新后查看当前生效版本') from exc


def rollback(db, target, user):
    """回退到指定版本（通常是被替换的 v1）；历史试验与简报仍按各自固定版本复现。"""
    current = active_rule(db)
    if current is not None and target.id == current.id:
        raise HTTPException(409, '该版本已经是当前生效版本')
    if target.status not in ('retired', 'candidate'):
        raise HTTPException(409, '只能回退到候选或已退役版本')
    now = time.time()
    if current is not None:
        current.is_active = False
        current.status = 'retired'
        current.retired_at = now
        db.flush()
    target.is_active = True
    target.status = 'active'
    target.activated_at = now
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, '已有其他版本先完成切换，请刷新后查看当前生效版本') from exc
