"""字段检索对比实验：关键词 vs 向量 vs 混合。用数据决定检索方案。
本机运行(向量需 sentence-transformers)：
  pip install sentence-transformers
  python exp_retrieval.py
"""
import config
config.DB_PATH = "data.db"
import retriever

TESTS = [
 ("脑积水","lateral_ventricle"),("脑室大小","lateral_ventricle"),
 ("胎龄","gestational_age"),("GA","gestational_age"),
 ("脑子多大","cerebrum"),("小脑大小","cerebellum"),
 ("脑沟深浅","sulcal_depth"),("大脑弯曲程度","curvature"),
 ("左右不对称","asymmetry"),("皮层多厚","cortical_thickness"),
 ("梭状回复杂度","FD_roi_055"),("海马分形","海马"),
]

def hit(method_rows, correct):
    return any(correct in f for f, t, u in method_rows)

def main():
    rows = retriever._load_fields()
    kw = sum(hit(retriever.keyword_search(q, rows), c) for q, c in TESTS)
    ve = sum(hit(retriever.vector_search(q, k=5), c) for q, c in TESTS)
    hy = sum(hit(retriever.hybrid_search(q), c) for q, c in TESTS)
    n = len(TESTS)
    vec_ok = retriever._get_vec() is not False
    print(f"关键词      : {kw}/{n} = {kw/n:.0%}")
    print(f"向量 Hit@5  : {ve}/{n} = {ve/n:.0%}" + ("" if vec_ok else "  (未装 sentence-transformers，向量未启用)"))
    print(f"混合(向量+关键词): {hy}/{n} = {hy/n:.0%}")
    if vec_ok:
        print("\n逐题(关键词/向量/混合):")
        for q, c in TESTS:
            k = hit(retriever.keyword_search(q, rows), c)
            v = hit(retriever.vector_search(q, k=5), c)
            h = hit(retriever.hybrid_search(q), c)
            print(f"  {q:10} {'✅' if k else '❌'} {'✅' if v else '❌'} {'✅' if h else '❌'}")

if __name__ == "__main__":
    main()
