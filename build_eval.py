"""构建评估集：定义题目+参考SQL/口径，执行得 gold，冻结成 eval_cases.json。
覆盖业内(Spider/BIRD)常见评测维度：执行准确率、同义词鲁棒性、隐式列/模式链接、
领域知识、SQL复杂度、脏数据/空值、不可答防幻觉。每题带 angle 标注所测维度。
判分类型 check：value / value_list / group / corr / clarify / transparency / unanswerable
"""
import sqlite3, json
import pandas as pd
con = sqlite3.connect("file:data.db?mode=ro&immutable=1", uri=True)
def one(sql):  return con.execute(sql).fetchone()[0]
def gid(sql):  return con.execute(sql).fetchone()[0]
def ids(sql):  return [r[0] for r in con.execute(sql).fetchall()]
def corr(sql,x,y):
    rows=con.execute(sql).fetchall(); cols=[d[0] for d in con.execute(sql).description]
    return round(float(pd.DataFrame(rows,columns=cols)[x].corr(pd.DataFrame(rows,columns=cols)[y])),3)
J="subjects s JOIN brain_features b ON s.subject_id=b.subject_id"
cases=[]
def add(qid,q,cat,check,gold,angle="执行准确率",ref=""):
    cases.append(dict(id=qid,question=q,category=cat,check=check,gold=gold,angle=angle,ref_sql=ref))

# ===== 原 15 题(执行准确率为主) =====
add("v1","广州一共有多少个体","simple","value", one("SELECT COUNT(*) FROM subjects WHERE center='广州'"))
add("v2","华西有多少个体","simple","value", one("SELECT COUNT(*) FROM subjects WHERE center='华西'"))
add("v3","孕龄大于30周的个体有多少个","filter","value", one("SELECT COUNT(*) FROM subjects WHERE age_known=1 AND gestational_age>30"))
add("v4","四川haste序列个体的左小脑体积均值(保留2位)","agg_join","value", round(one(f"SELECT AVG(b.cerebellum_left_volume_ml) FROM {J} WHERE s.center='四川' AND s.modality='haste'"),2))
add("v5","华西30周以上个体的左侧皮层平均厚度均值(保留2位)","agg_join","value", round(one(f"SELECT AVG(b.cortical_thickness_mean_left_mm) FROM {J} WHERE s.center='华西' AND s.age_known=1 AND s.gestational_age>30"),2))
add("v6","第三脑室体积的整体均值(保留3位)","agg","value", round(one("SELECT AVG(third_ventricle_volume_ml) FROM brain_features"),3))
add("v7","左梭状回分形维数最高的是哪个个体","specific_region","value", gid('SELECT subject_id FROM brain_features ORDER BY "FD_roi_055_左梭状回" DESC LIMIT 1'))
add("v8","侧脑室总体积(左+右)最大的个体","compute_col","value", gid(f"SELECT s.subject_id FROM {J} ORDER BY (b.lateral_ventricle_left_volume_ml+b.lateral_ventricle_right_volume_ml) DESC LIMIT 1"))
add("g1","每个中心各有多少个体","group","group", {r[0]:r[1] for r in con.execute("SELECT center,COUNT(*) FROM subjects GROUP BY center")})
add("g2","四川各模态的左小脑体积均值","group","group", {r[0]:round(r[1],2) for r in con.execute(f"SELECT s.modality,AVG(b.cerebellum_left_volume_ml) FROM {J} WHERE s.center='四川' GROUP BY s.modality")})
add("c1","小脑体积和孕龄有没有相关性","correlation","corr", corr(f"SELECT s.gestational_age AS ga,(b.cerebellum_left_volume_ml+b.cerebellum_right_volume_ml) AS v FROM {J} WHERE s.age_known=1","ga","v"))
add("c2","侧脑室体积和孕龄有没有相关性","correlation","corr", corr(f"SELECT s.gestational_age AS ga,(b.lateral_ventricle_left_volume_ml+b.lateral_ventricle_right_volume_ml) AS v FROM {J} WHERE s.age_known=1","ga","v"))
add("q1","四川的数据有多少","ambiguous","clarify", None, "歧义澄清")
add("q2","皮层厚度最大的10个个体","ambiguous","clarify", None, "歧义澄清")
add("t1","所有个体的平均孕龄是多少(保留2位)","missing_data","transparency", round(one("SELECT AVG(gestational_age) FROM subjects WHERE age_known=1"),2), "缺失数据说明")

# ===== 新增：同义词鲁棒性(Spider-Syn)——用户词≠字段词 =====
add("syn1","孕周超过35周的有几个","filter","value", one("SELECT COUNT(*) FROM subjects WHERE age_known=1 AND gestational_age>35"), "同义词鲁棒性")
add("syn2","华西那边侧脑室总体积最大的个体是谁","compute_col","value", gid(f"SELECT s.subject_id FROM {J} WHERE s.center='华西' ORDER BY (b.lateral_ventricle_left_volume_ml+b.lateral_ventricle_right_volume_ml) DESC LIMIT 1"), "同义词鲁棒性")
add("syn3","各个模态的样本数分别是多少","group","group", {r[0]:r[1] for r in con.execute("SELECT modality,COUNT(*) FROM subjects GROUP BY modality")}, "同义词鲁棒性")

# ===== 新增：隐式列/模式链接(Spider-Realistic)——不点名列 =====
add("imp1","哪个胎儿的大脑最大","compute_col","value", gid(f"SELECT s.subject_id FROM {J} ORDER BY (b.cerebrum_left_volume_ml+b.cerebrum_right_volume_ml) DESC LIMIT 1"), "隐式列/模式链接")
add("imp2","小脑最小的个体是哪个","compute_col","value", gid(f"SELECT s.subject_id FROM {J} ORDER BY (b.cerebellum_left_volume_ml+b.cerebellum_right_volume_ml) ASC LIMIT 1"), "隐式列/模式链接")
add("imp3","大脑左右最不对称的个体","specific_region","value", gid("SELECT subject_id FROM brain_features ORDER BY ABS(cerebrum_volume_hemispheric_asymmetry_index) DESC LIMIT 1"), "隐式列/模式链接")

# ===== 新增：领域知识(Spider-DK) =====
add("dk1","可能有脑室扩张风险的前3个个体(按侧脑室总体积)","compute_col","value_list", ids(f"SELECT s.subject_id FROM {J} ORDER BY (b.lateral_ventricle_left_volume_ml+b.lateral_ventricle_right_volume_ml) DESC LIMIT 3"), "领域知识"),
add("dk2","皮层最厚的个体(左右平均)","compute_col","value", gid(f"SELECT s.subject_id FROM {J} ORDER BY (b.cortical_thickness_mean_left_mm+b.cortical_thickness_mean_right_mm)/2 DESC LIMIT 1"), "领域知识")

# ===== 新增：更高 SQL 复杂度 =====
add("h1","孕龄28到34周之间、华西的个体有几个","hard","value", one("SELECT COUNT(*) FROM subjects WHERE center='华西' AND age_known=1 AND gestational_age BETWEEN 28 AND 34"), "SQL复杂度")
add("h2","四川30周以上、各模态的左小脑体积均值","hard","group", {r[0]:round(r[1],2) for r in con.execute(f"SELECT s.modality,AVG(b.cerebellum_left_volume_ml) FROM {J} WHERE s.center='四川' AND s.age_known=1 AND s.gestational_age>30 GROUP BY s.modality")}, "SQL复杂度")
add("h3","左右小脑体积都大于5的个体有几个","hard","value", one("SELECT COUNT(*) FROM brain_features WHERE cerebellum_left_volume_ml>5 AND cerebellum_right_volume_ml>5"), "SQL复杂度")
add("h4","皮层厚度左右差异(绝对值)最大的个体","hard","value", gid("SELECT subject_id FROM brain_features ORDER BY ABS(cortical_thickness_mean_left_mm-cortical_thickness_mean_right_mm) DESC LIMIT 1"), "SQL复杂度")
# 各中心孕龄最大的个体(分组内求最值)
centers=[r[0] for r in con.execute("SELECT DISTINCT center FROM subjects WHERE center!='未标注中心(自重建批)'")]
argmax={c: gid(f"SELECT subject_id FROM subjects WHERE center='{c}' AND age_known=1 ORDER BY gestational_age DESC LIMIT 1") for c in centers}
add("h5","广州、华西、四川各自孕龄最大的个体分别是谁","hard","value_list", list(argmax.values()), "SQL复杂度")

# ===== 新增：脏数据/空值(BIRD) =====
add("n1","孕龄缺失(未知)的个体有多少","missing_data","value", one("SELECT COUNT(*) FROM subjects WHERE age_known=0"), "脏数据/空值")
add("n2","左延髓分形维数为空(缺失)的个体有多少","missing_data","value", one('SELECT COUNT(*) FROM brain_features WHERE "FD_roi_098_左延髓" IS NULL'), "脏数据/空值")

# ===== 新增：不可答/防幻觉 =====
add("u1","胎儿的性别分布是怎样的","unanswerable","unanswerable", None, "不可答/防幻觉")
add("u2","母亲年龄和脑体积有关系吗","unanswerable","unanswerable", None, "不可答/防幻觉")
add("u3","各个体的出生体重是多少","unanswerable","unanswerable", None, "不可答/防幻觉")

# ===== 新增：相关性扩展 & 歧义扩展 =====
add("c3","皮层厚度和孕龄有没有关系","correlation","corr", corr(f"SELECT s.gestational_age AS ga,(b.cortical_thickness_mean_left_mm+b.cortical_thickness_mean_right_mm)/2 AS v FROM {J} WHERE s.age_known=1","ga","v"), "执行准确率")
add("c4","大脑体积和小脑体积相关吗","correlation","corr", corr(f"SELECT (b.cerebrum_left_volume_ml+b.cerebrum_right_volume_ml) AS a,(b.cerebellum_left_volume_ml+b.cerebellum_right_volume_ml) AS c FROM {J}","a","c"), "执行准确率")
add("q3","体积最大的个体是哪个","ambiguous","clarify", None, "歧义澄清")

# 清理可能的元组包裹(某行末尾多了逗号)
cases=[c[0] if isinstance(c,tuple) else c for c in cases]
json.dump(cases, open("eval_cases.json","w",encoding="utf-8"), ensure_ascii=False, indent=2)
from collections import Counter
print(f"评估集共 {len(cases)} 题")
print("按评测维度(angle):", dict(Counter(c['angle'] for c in cases)))
print("按判分类型(check):", dict(Counter(c['check'] for c in cases)))
print("\n新增题 gold 抽样:")
for c in cases[15:]:
    print(f"  [{c['id']}] {c['angle']:12} {c['check']:11} {c['question'][:20]:22} -> {str(c['gold'])[:40]}")
