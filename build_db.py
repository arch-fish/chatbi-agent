"""
build_db.py —— 从原始 Excel/CSV 构建 ChatBI 用的 SQLite 数据库。

设计目标：把分散、字段异构的原始表，清洗成 agent 好查询、语义清晰的规范化库。
产出 4 张表：
  subjects        个体主表（过滤维度：中心、孕龄、模态）
  brain_features  形态学特征宽表（度量维度：156 个指标）
  semantic_dict   语义字典（字段 -> 业务术语/单位/口径），喂给 LLM 对齐语义
  (clinical 临床表留待后续，需从医院表脱敏抽取)
"""
import pandas as pd
import sqlite3
import re
import os

HERE = os.path.dirname(os.path.abspath(__file__))
EXCEL = os.path.join(HERE, "..", "excel")
FEATURE_CSV = os.path.join(EXCEL, "我整理的表", "ALL_subjects_脑定量表_对齐参考表.csv")
# 注意：SQLite 不能直接建在挂载的 Windows 文件夹上(文件锁不支持 -> disk I/O error)。
# 先在沙盒本地磁盘建库，最后再把成品 .db 拷回项目文件夹。
BUILD_PATH = "/tmp/data.db"
DB_PATH = os.path.join(HERE, "data.db")

# ---------- 1. 读特征表（唯一真源：这 1761 个个体是我们真正有分析价值的群体） ----------
df = pd.read_csv(FEATURE_CSV)
assert df["filename"].is_unique, "filename 必须唯一，用作主键"

# ---------- 2. 数据清洗：把脏 source 归一成干净的分析维度 ----------
def to_center(source: str) -> str:
    s = source.lower()
    if s.startswith("guangzhou"):
        return "广州"
    if s.startswith("huaxi"):
        return "华西"
    if s.startswith("sichuan"):
        return "四川"
    if s.startswith("self_recon"):
        return "未标注中心(自重建批)"  # self_recon 是重建批次，原始未标注中心，不臆造
    return "其他"

def to_modality(filename: str) -> str:
    tok = filename.lower()
    if "haste" in tok:
        return "haste"
    if "trufi" in tok:
        return "trufi"
    if "btfe" in tok:
        return "btfe"
    return "未知"

subjects = pd.DataFrame({
    "subject_id": df["filename"],
    "center": df["source"].map(to_center),
    "source_batch": df["source"],                 # 保留原始批次，便于溯源
    "modality": df["filename"].map(to_modality),
    "gestational_age": df["gestational_age"],      # 缺失保留为 NULL，不填补、不删行
    # age_known：source 带 noage 或 孕龄为空 => 未知。决定(b)：标注而非静默排除
    "age_known": (~df["source"].str.contains("noage")) & (df["gestational_age"].notna()),
})
subjects["age_known"] = subjects["age_known"].astype(int)

# ---------- 3. 特征宽表：主键 + 156 个指标列，原样保真 ----------
feature_cols = [c for c in df.columns if c not in ("filename", "source", "gestational_age")]
brain = df[["filename"] + feature_cols].rename(columns={"filename": "subject_id"})

# ---------- 4. 语义字典：LLM 面向 156 列的"翻译层"，解决字段易选错/口径不清 ----------
sem_rows = []
def add(field, term, unit, definition, category):
    sem_rows.append(dict(field_name=field, chinese_term=term, unit=unit,
                         definition=definition, category=category))

# 维度字段
add("subject_id", "个体编号", "", "唯一标识，来自影像文件名", "维度")
add("center", "中心/来源", "", "数据来源中心：广州/华西/四川/未标注", "维度")
add("modality", "模态/序列", "", "MRI 序列类型：haste/trufi/btfe", "维度")
add("gestational_age", "孕龄/孕周", "周", "胎儿孕龄，部分个体缺失(标为未知)", "维度")
add("age_known", "孕龄是否已知", "0/1", "1=有孕龄记录，0=原始未记录", "维度")

# 核心形态学指标（人工给准口径——这是 ChatBI 语义对齐的关键）
core = {
 "cerebrum_left_volume_ml": ("左侧大脑体积", "ml"),
 "cerebrum_right_volume_ml": ("右侧大脑体积", "ml"),
 "cerebellum_left_volume_ml": ("左侧小脑体积", "ml"),
 "cerebellum_right_volume_ml": ("右侧小脑体积", "ml"),
 "lateral_ventricle_left_volume_ml": ("左侧侧脑室体积", "ml"),
 "lateral_ventricle_right_volume_ml": ("右侧侧脑室体积", "ml"),
 "third_ventricle_volume_ml": ("第三脑室体积", "ml"),
 "fourth_ventricle_volume_ml": ("第四脑室体积", "ml"),
 "pial_surface_area_left_mm2": ("左侧软膜表面积", "mm2"),
 "pial_surface_area_right_mm2": ("右侧软膜表面积", "mm2"),
 "pial_mean_curvature_mean_left": ("左侧软膜平均曲率(均值)", ""),
 "pial_mean_curvature_mean_right": ("右侧软膜平均曲率(均值)", ""),
 "pial_gaussian_curvature_mean_left": ("左侧软膜高斯曲率(均值)", ""),
 "pial_gaussian_curvature_mean_right": ("右侧软膜高斯曲率(均值)", ""),
 "pial_sulcal_depth_mean_left": ("左侧脑沟深度(均值)", ""),
 "pial_sulcal_depth_mean_right": ("右侧脑沟深度(均值)", ""),
 "white_surface_area_left_mm2": ("左侧白质表面积", "mm2"),
 "white_surface_area_right_mm2": ("右侧白质表面积", "mm2"),
 "cerebrum_volume_hemispheric_asymmetry_index": ("大脑体积半球不对称指数", ""),
 "cortical_thickness_mean_left_mm": ("左侧皮层平均厚度", "mm"),
 "cortical_thickness_mean_right_mm": ("右侧皮层平均厚度", "mm"),
}
for f, (term, unit) in core.items():
    add(f, term, unit, "形态学量化指标", "形态学")

# 分形维数：组织级 + 脑区级，按命名规律批量生成
for c in feature_cols:
    if c.startswith("FD_tissue_"):
        name = re.sub(r"^FD_tissue_\d+_", "", c)
        add(c, f"{name}分形维数", "", "组织级分形维数(FD)，反映结构复杂度", "FD-组织")
    elif c.startswith("FD_roi_"):
        name = re.sub(r"^FD_roi_\d+_", "", c)
        add(c, f"{name}分形维数", "", "精细脑区级分形维数(FD)", "FD-脑区")

semantic = pd.DataFrame(sem_rows)

# ---------- 5. 写入 SQLite ----------
if os.path.exists(BUILD_PATH):
    os.remove(BUILD_PATH)
con = sqlite3.connect(BUILD_PATH)
subjects.to_sql("subjects", con, index=False)
brain.to_sql("brain_features", con, index=False)
semantic.to_sql("semantic_dict", con, index=False)
# 主键/索引：subject_id 常用于 join 和过滤
con.execute("CREATE UNIQUE INDEX idx_subj ON subjects(subject_id)")
con.execute("CREATE UNIQUE INDEX idx_feat ON brain_features(subject_id)")
con.execute("CREATE INDEX idx_center ON subjects(center)")
con.commit()

print("subjects:", len(subjects), "行")
print("brain_features:", len(brain), "行 ×", len(brain.columns), "列")
print("semantic_dict:", len(semantic), "条")
print("中心分布:", subjects["center"].value_counts().to_dict())
print("模态分布:", subjects["modality"].value_counts().to_dict())
print("孕龄已知:", int(subjects["age_known"].sum()), "/", len(subjects))
con.close()

# 拷回项目文件夹（纯文件复制，无锁问题）
import shutil
shutil.copy(BUILD_PATH, DB_PATH)
print("OK ->", DB_PATH)
