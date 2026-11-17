from fastapi import APIRouter, Depends
from sqlalchemy import select
from src.config.database import get_db
from src.models import RuleVersion, ShadowReplay
from src.schemas.rule import RuleCreateInput, ReplayInput
from src.middlewares.auth import current_user, can_write, admin_only
from src.services import rules
from src.services.audit import record
from src.utils.serialization import rule_dict, replay_dict
router = APIRouter(prefix='/rules')


@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    rows = db.scalars(select(RuleVersion).order_by(RuleVersion.id.desc())).all()
    data = [rule_dict(r) for r in rows]
    for item, r in zip(data, rows):
        item['replay_stats'] = {
            'completed': len([x for x in r.replays if x.status == 'completed']),
            'pending': len([x for x in r.replays if x.status in ('pending', 'running')]),
            'failed': len([x for x in r.replays if x.status == 'failed']),
        }
    return data


@router.get('/active')
def active(db=Depends(get_db), u=Depends(current_user)):
    r = rules.active_rule(db)
    return rule_dict(r) if r else None


@router.post('', status_code=201)
def create(data: RuleCreateInput, db=Depends(get_db), u=Depends(can_write)):
    r = rules.create_candidate(db, data, u)
    replay_ids = [x.id for x in db.scalars(select(ShadowReplay).where(
        ShadowReplay.rule_version_id == r.id, ShadowReplay.status == 'pending'))]
    record(db, u.email, 'rule.create', {'id': r.id, 'code': r.code, 'engine': r.engine_key, 'jobs': data.job_ids})
    db.commit()
    rules.enqueue_replays(replay_ids)
    return rule_dict(r)


@router.get('/{id}')
def detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    r = rules.get_rule(db, id)
    item = rule_dict(r)
    item['replays'] = [replay_dict(x) for x in sorted(r.replays, key=lambda x: x.id)]
    return item


@router.post('/{id}/replays', status_code=201)
def replays(id: int, data: ReplayInput, db=Depends(get_db), u=Depends(can_write)):
    r = rules.get_rule(db, id)
    ids = rules.create_replays(db, r, data.job_ids, u)
    record(db, u.email, 'replay.requested', {'rule': r.code, 'jobs': data.job_ids})
    db.commit()
    rules.enqueue_replays(ids)
    return [replay_dict(db.get(ShadowReplay, i)) for i in ids]


@router.get('/{id}/replays')
def replay_list(id: int, db=Depends(get_db), u=Depends(current_user)):
    r = rules.get_rule(db, id)
    return [replay_dict(x) for x in sorted(r.replays, key=lambda x: x.id)]


@router.post('/{id}/activate')
def activate(id: int, db=Depends(get_db), u=Depends(admin_only)):
    r = rules.get_rule(db, id)
    rules.activate(db, r, u)
    record(db, u.email, 'rule.activate', {'id': r.id, 'code': r.code})
    db.commit()
    return rule_dict(db.get(RuleVersion, r.id))


@router.post('/{id}/rollback')
def rollback(id: int, db=Depends(get_db), u=Depends(admin_only)):
    r = rules.get_rule(db, id)
    rules.rollback(db, r, u)
    record(db, u.email, 'rule.rollback', {'id': r.id, 'code': r.code})
    db.commit()
    return rule_dict(db.get(RuleVersion, r.id))
