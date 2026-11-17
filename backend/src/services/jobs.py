import time
from fastapi import HTTPException
from redis import Redis
from sqlalchemy import select
from src.config.settings import REDIS_URL
from src.models import Dataset, Job
from src.services.business import metadata
from src.services import rules
def create(db, data, user):
    if not db.get(Dataset,data.dataset_id): raise HTTPException(404,'数据批次不存在')
    allowed={p['key']:p for p in metadata().get('parameters',[])}
    if set(data.params)-set(allowed): raise HTTPException(422,'包含未知分析参数')
    params={k:p['default'] for k,p in allowed.items()}
    params.update(data.params)
    for key,p in allowed.items():
        v=params[key]
        if p['type']=='number':
            try:
                v=float(v)
                if not (p.get('min',-1e9)<=v<=p.get('max',1e9)): raise ValueError()
                params[key]=v
            except (ValueError,TypeError): raise HTTPException(422, f'{p["label"]} 超出范围或非数值')
        elif str(v) not in [str(o['value']) for o in p.get('options',[])]:
            raise HTTPException(422,f'{p["label"]} 不是有效选项')
    # 创建时固定生效版本；之后排队、恢复、版本切换都不改版。
    # 与版本切换并发时由数据库事务的先完成者决定本试验归属哪个版本。
    rule=rules.active_rule(db)
    j=Job(name=data.name, dataset_id=data.dataset_id, params=params, created_by=user.id,
          created_at=time.time(), status='queued', rule_version_id=rule.id if rule else None)
    db.add(j); db.flush()
    return j
def enqueue(job_id):
    try:
        r=Redis.from_url(REDIS_URL); r.rpush('analysis:queue',job_id); r.close()
    except Exception:
        pass # SQL queued status is the durable fallback
