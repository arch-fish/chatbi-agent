"""字段检索：混合检索(向量 + 关键词)。
- 关键词(二元词匹配)：字面精确、无需模型、始终可用。
- 向量(语义)：跨字面(脑积水↔侧脑室)，需 sentence-transformers；未安装则自动降级为纯关键词。
向量字段索引在首次使用时预计算并缓存(单例)，避免每次查询重复编码。"""
import sqlite3
import config

_VEC = None  # 缓存 (model, rows, embs)；False 表示不可用

def _load_fields():
    con = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro&immutable=1", uri=True)
    rows = con.execute("SELECT field_name, chinese_term, unit FROM semantic_dict").fetchall()
    con.close()
    return rows

def _grams(kw):
    kw = kw.strip()
    return {kw} | ({kw[i:i+2] for i in range(len(kw) - 1)} if len(kw) >= 2 else set())

def keyword_search(kw, rows):
    grams = _grams(kw)
    return [(f, t, u) for f, t, u in rows if any(g in (f + " " + (t or "")) for g in grams)]

def _get_vec():
    global _VEC
    if _VEC is not None:
        return _VEC
    rows = _load_fields()
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
        terms = [t or f for f, t, u in rows]
        embs = np.array(model.encode(terms, normalize_embeddings=True))
        _VEC = (model, rows, embs)
    except Exception:
        _VEC = False   # 没装模型 -> 降级
    return _VEC

def vector_search(kw, k=8):
    vec = _get_vec()
    if not vec:
        return []
    import numpy as np
    model, rows, embs = vec
    qe = model.encode([kw], normalize_embeddings=True)[0]
    idx = np.argsort(embs @ qe)[::-1][:k]
    return [rows[i] for i in idx]

def hybrid_search(kw, k=8, limit=25):
    """向量 top-k(语义) + 关键词(字面) 合并去重。向量优先(补语义)，再补关键词命中。"""
    rows = _load_fields()
    seen, merged = set(), []
    for f, t, u in vector_search(kw, k) + keyword_search(kw, rows):
        if f not in seen:
            seen.add(f); merged.append((f, t, u))
    return merged[:limit]
