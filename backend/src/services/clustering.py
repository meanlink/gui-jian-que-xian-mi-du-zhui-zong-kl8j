"""一维 DBSCAN 聚类引擎与计算口径注册表。

规则版本通过 engine_key + config 选择口径。引擎只负责聚类，参数与数据校验
仍由 services.business.analyze 统一完成，保证不同版本的失败态完全一致。
"""
import numpy as np

# 口径 v1：所有点均可成为核心点，与 sklearn 一维 DBSCAN 结果逐项一致。
BASELINE_ENGINE = "baseline_1d_dbscan"
# 候选口径：仅复核等级达到 core_min_severity 的点可成为核心点，
# 低等级密集点退为边界点（仍可归入缺陷带）或噪声点。
SEVERITY_CORE_ENGINE = "severity_core_1d_dbscan"

ENGINES = {
    BASELINE_ENGINE: {
        "label": "基础一维DBSCAN口径",
        "description": "邻域内点数达到 min_points 即可成为核心点，等级不参与聚类。",
        "config_fields": [],
    },
    SEVERITY_CORE_ENGINE: {
        "label": "核心点等级约束口径",
        "description": "邻域点数达标且复核等级不低于下限的点才能成为核心点；低等级点仍可作为边界点归入缺陷带。",
        "config_fields": [{"key": "core_min_severity", "label": "核心点最低复核等级", "type": "number", "min": 2, "max": 5, "default": 4}],
    },
}


def dbscan_1d(x, eps, min_samples, core_eligible=None):
    """一维 DBSCAN，返回 (labels, core_mask)，顺序与输入 x 一致。

    无 core_eligible 时与 ``sklearn.cluster.DBSCAN`` 在一维数据上的标签和
    核心点掩码逐项等价（已用大量随机样本核对）。传入布尔掩码时，密度达标但
    不合格的点不会成为核心点，只可能作为边界点被邻近核心点收入簇中。
    """
    x = np.asarray(x, dtype=float)
    n = len(x)
    order = np.argsort(x, kind="stable")
    pos = x[order]
    left = np.searchsorted(pos, pos - eps, side="left")
    right = np.searchsorted(pos, pos + eps, side="right")
    counts = right - left
    if core_eligible is None:
        core_sorted = counts >= min_samples
    else:
        core_sorted = (counts >= min_samples) & np.asarray(core_eligible, dtype=bool)[order]
    # 并查集按“排序后位置”编号，不能与原始点下标混用。
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    core_positions = np.flatnonzero(core_sorted)
    for k in core_positions:
        for m in range(int(k) + 1, int(right[k])):
            if core_sorted[m]:
                union(int(k), int(m))
    # 簇编号按各簇“最早出现的核心点（原始下标最小）”排序，复现 sklearn 处理顺序。
    raw_of_core = {int(k): find(int(k)) for k in core_positions}
    origin = {}
    for k, raw in raw_of_core.items():
        orig = int(order[k])
        if raw not in origin or orig < origin[raw]:
            origin[raw] = orig
    ordered_raw = sorted(origin, key=lambda r: origin[r])
    raw_to_label = {raw: lab for lab, raw in enumerate(ordered_raw)}
    labels = np.full(n, -1, dtype=int)
    core_mask = np.zeros(n, dtype=bool)
    for k in core_positions:
        orig = int(order[k])
        labels[orig] = raw_to_label[raw_of_core[int(k)]]
        core_mask[orig] = True
    # 边界点同时邻近多个簇时，归入最早核心点（原始下标最小）所在的簇。
    for si in range(n):
        if core_sorted[si]:
            continue
        best_raw = None
        best_origin = None
        for m in range(int(left[si]), int(right[si])):
            if core_sorted[m]:
                raw = raw_of_core[int(m)]
                if best_origin is None or origin[raw] < best_origin:
                    best_origin = origin[raw]
                    best_raw = raw
        if best_raw is not None:
            labels[int(order[si])] = raw_to_label[best_raw]
    return labels, core_mask


def validate_config(engine_key, config):
    """校验候选口径配置，返回规范化后的 config。"""
    if engine_key not in ENGINES:
        raise ValueError("未知计算口径，无法创建规则版本。")
    if engine_key == BASELINE_ENGINE:
        # 基础口径没有可调参数，忽略调用方传入的任何键。
        return {}
    config = dict(config or {})
    if engine_key == SEVERITY_CORE_ENGINE:
        try:
            threshold = int(config.get("core_min_severity", 4))
        except (TypeError, ValueError):
            raise ValueError("核心点最低复核等级必须是2~5的整数。")
        if threshold != config.get("core_min_severity", 4) or not 2 <= threshold <= 5:
            raise ValueError("核心点最低复核等级必须是2~5的整数。")
        config["core_min_severity"] = threshold
    return config


def eligibility(engine_key, config, severity):
    """返回核心点资格掩码；基础口径返回 None 表示全部合格。"""
    if engine_key == BASELINE_ENGINE:
        return None
    if engine_key == SEVERITY_CORE_ENGINE:
        threshold = int((config or {}).get("core_min_severity", 4))
        return np.asarray(severity, dtype=float) >= threshold
    raise ValueError("未知计算口径。")


def method_text(engine_key, config):
    """供结果页与简报复现的口径说明。"""
    base = "仅按同一线路方向的沿线里程距离做一维DBSCAN；eps单位为米，min_samples包含自身；无密度支撑的点标为噪声，横向偏差和等级仅用于结果解释。"
    if engine_key == SEVERITY_CORE_ENGINE:
        threshold = int((config or {}).get("core_min_severity", 4))
        return base + f"本口径要求核心点复核等级不低于{threshold}级；低于该等级的密集点只能作为边界点，不能再向外扩展密度可达链。"
    return base
