import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report, RuleVersion, ShadowReplay
from src.services.business import analyze
from src.services.reports import deliver
from src.services import rules
from src.services.audit import record
logging.basicConfig(level=logging.INFO)
def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        j.status='running'; db.commit()
        try:
            d=db.get(Dataset,j.dataset_id)
            # 始终使用试验创建时固定的规则版本；排队与恢复都不换版。
            rule=db.get(RuleVersion,j.rule_version_id) if j.rule_version_id else None
            result=analyze(d.records,j.params,rules.snapshot(rule) if rule else None)
            json.dumps(result,allow_nan=False)
            j.result=result;j.status='completed';j.finished_at=time.time()
            record(db,'worker','job.completed',{'id':j.id,'rule':rule.code if rule else None})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status='failed';j.error=str(e)[:990];j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        db.commit()
def tick():
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
        # Redis 丢失时，pending 回放由 SQL 状态兜底继续执行。
        replays=list(db.scalars(select(ShadowReplay.id).where(ShadowReplay.status=='pending').limit(3)))
    for job_id in queued:execute(job_id)
    for replay_id in replays:rules.run_replay(replay_id)
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled==True,Report.next_run<=time.time())):
            d=deliver(db,r)
            if d:record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id})
        db.commit()
def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    # 恢复只重新排队，不改变试验固定的规则版本；已完成回放不重复生成。
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            j.status='queued';record(db,'worker','job.recovered',{'id':j.id})
        for rp in db.scalars(select(ShadowReplay).where(ShadowReplay.status=='running')):
            rp.status='pending';record(db,'worker','replay.recovered',{'id':rp.id})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop(['analysis:queue','replay:queue'],timeout=1)
            if item:
                queue, payload = item[0], item[1]
                if queue == b'analysis:queue':
                    execute(int(payload))
                else:
                    rules.run_replay(int(payload))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
