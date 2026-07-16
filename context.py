"""构建喂给 LLM 的“数据库说明书”。
为什么需要：LLM 不知道你的表结构和字段口径。给它准确的 schema+语义，
能大幅减少幻觉(瞎编列名)和选错列。这就是解决 ChatBI“语义对齐”的地方。
为什么不把 154 列全塞：token 贵，且上下文越长越容易选错。只给维度+核心形态学，
FD 这类 128 列做“摘要+规律”说明，需要具体列时后续(agent版)再用检索。"""
from db import get_conn

def build_context(db_path):
    con = get_conn(db_path); cur = con.cursor()
    L = []
    L.append("【表 subjects】个体维度表，用于过滤(WHERE)。字段：")
    for r in cur.execute("SELECT field_name,chinese_term,unit,definition FROM semantic_dict WHERE category='维度'"):
        unit = f"({r[2]})" if r[2] else ""
        L.append(f"  - {r[0]} = {r[1]}{unit}：{r[3]}")
    L.append("【表 brain_features】形态学度量表，用于聚合/计算。主键 subject_id 与 subjects 关联(JOIN)。核心字段：")
    for r in cur.execute("SELECT field_name,chinese_term,unit FROM semantic_dict WHERE category='形态学'"):
        unit = f"({r[2]})" if r[2] else ""
        L.append(f"  - {r[0]} = {r[1]}{unit}")
    nt = cur.execute("SELECT COUNT(*) FROM semantic_dict WHERE category='FD-组织'").fetchone()[0]
    nr = cur.execute("SELECT COUNT(*) FROM semantic_dict WHERE category='FD-脑区'").fetchone()[0]
    L.append(f"【分形维数(FD)】brain_features 还有组织级 {nt} 列(FD_tissue_*)、脑区级 {nr} 列(FD_roi_*)，"
             f"列名含中文脑区，如 FD_roi_055_左梭状回、FD_tissue_004_皮质（左）。含中文列名在SQL里要用双引号包裹。")
    con.close()
    return "\n".join(L)
