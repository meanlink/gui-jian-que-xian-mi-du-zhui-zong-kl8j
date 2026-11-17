import time
import logging
from sqlalchemy import text
from sqlalchemy import select, inspect
from src.config.database import Base, engine, Session
from src import models
from src.services.clustering import BASELINE_ENGINE


def _backfill_point_assignments(db, baseline):
    """旧结果缺少逐点快照时，用固定 v1 口径补齐，保证影子回放能逐点比对。

    只补 point_assignments 与 rule 两个新字段，不改任何既有结果字段；
    单个任务失败只记录日志、不阻断迁移。
    """
    from src.services.business import analyze
    from src.services import rules
    backfilled = 0
    for job in db.scalars(select(models.Job).where(models.Job.status == 'completed')):
        result = job.result or {}
        if result.get('point_assignments'):
            continue
        try:
            if not job.dataset_id:
                logging.warning('skip point_assignments backfill: job %s has no dataset', job.id)
                continue
            dataset = db.get(models.Dataset, job.dataset_id)
            if dataset is None:
                # 数据批次已不存在时无法重算；保留原结果，不阻断迁移。
                logging.warning('skip point_assignments backfill: dataset %s missing for job %s',
                                job.dataset_id, job.id)
                continue
            recomputed = analyze(dataset.records, job.params, rules.snapshot(baseline))
            # 仅注入新字段，保持 summary/table/chart 等历史结果原样。
            # 必须赋新 dict：模型是普通 JSON 列，原地改同一引用不会被标记为脏。
            job.result = {
                **(job.result or {}),
                'point_assignments': recomputed['point_assignments'],
                'rule': recomputed['rule'],
            }
            backfilled += 1
        except Exception:
            logging.exception('backfill point_assignments failed for job %s', job.id)
    if backfilled:
        db.commit()
        print(f"backfilled point_assignments on {backfilled} historical jobs")


def migrate():
    Base.metadata.create_all(engine)
    # create_all 不会给已存在的表补列；老库升级时手动补 jobs.rule_version_id。
    job_columns = {col['name'] for col in inspect(engine).get_columns('jobs')}
    if 'rule_version_id' not in job_columns:
        with engine.begin() as conn:
            conn.execute(text('ALTER TABLE jobs ADD COLUMN rule_version_id INTEGER'))
    with engine.begin() as conn:
        # 同一时刻至多一个生效版本；候选与已退役版本 is_active=False，不受约束。
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_rule_versions_one_active "
            "ON rule_versions (is_active) WHERE is_active = true"
        ))
    with Session() as db:
        baseline = db.scalar(select(models.RuleVersion).where(models.RuleVersion.code == 'v1'))
        if baseline is None:
            # 内置 v1 基础口径：旧版维持原义，历史试验默认归属该版本。
            baseline = models.RuleVersion(
                code='v1', name='v1 基础密度口径',
                description='原始一维DBSCAN口径：邻域点数达标即可成为核心点，等级不参与聚类。历史试验与简报均按此版本复现。',
                engine_key=BASELINE_ENGINE, config={}, status='active', is_active=True,
                created_by=1, created_at=time.time(), activated_at=time.time(),
            )
            db.add(baseline)
            db.commit()
        # 历史已完成/排队中的试验固定到 v1，保证排队与恢复都不会悄悄换版。
        updated = db.query(models.Job).filter(models.Job.rule_version_id.is_(None)).update(
            {models.Job.rule_version_id: baseline.id}, synchronize_session=False
        )
        db.commit()
        if updated:
            print(f"backfilled rule_version_id on {updated} historical jobs")
        _backfill_point_assignments(db, baseline)


if __name__ == '__main__':
    migrate()
