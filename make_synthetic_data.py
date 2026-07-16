"""生成合成数据 data.db（脱敏用）：相同表结构、假 subject_id、随机数值，无任何 PII。
用途：让仓库在【不含真实医疗数据】的情况下也能跑通 Demo 与评测。
运行：python make_synthetic_data.py
"""
import sqlite3, random, os, re
random.seed(42)

CENTERS=["华西","四川","广州","未标注中心(自重建批)"]
MODS=["haste","trufi","btfe","未知"]
N=300
FEATURE_COLS=['subject_id', 'cerebrum_left_volume_ml', 'cerebrum_right_volume_ml', 'cerebellum_left_volume_ml', 'cerebellum_right_volume_ml', 'lateral_ventricle_left_volume_ml', 'lateral_ventricle_right_volume_ml', 'third_ventricle_volume_ml', 'fourth_ventricle_volume_ml', 'pial_surface_area_left_mm2', 'pial_surface_area_right_mm2', 'pial_mean_curvature_mean_left', 'pial_mean_curvature_mean_right', 'pial_gaussian_curvature_mean_left', 'pial_gaussian_curvature_mean_right', 'pial_sulcal_depth_mean_left', 'pial_sulcal_depth_mean_right', 'white_surface_area_left_mm2', 'white_surface_area_right_mm2', 'cerebrum_volume_hemispheric_asymmetry_index', 'cortical_thickness_mean_left_mm', 'cortical_thickness_mean_right_mm', 'FD_tissue_001_脑脊液', 'FD_tissue_003_皮质（右）', 'FD_tissue_004_皮质（左）', 'FD_tissue_005_白质（右）', 'FD_tissue_006_白质（左）', 'FD_tissue_007_侧脑室（右）', 'FD_tissue_008_侧脑室（左）', 'FD_tissue_010_中脑', 'FD_tissue_011_小脑（右）', 'FD_tissue_012_小脑（左）', 'FD_tissue_013_胼胝体', 'FD_tissue_014_壳核（右）', 'FD_tissue_015_壳核（左）', 'FD_tissue_016_丘脑（右）', 'FD_tissue_017_丘脑（左）', 'FD_tissue_018_第三脑室', 'FD_tissue_019_第四脑室', 'FD_roi_001_左中央前回', 'FD_roi_002_右中央前回', 'FD_roi_003_左额上回', 'FD_roi_004_右额上回', 'FD_roi_005_左额上回眶部', 'FD_roi_006_右额上回眶部', 'FD_roi_007_左额中回', 'FD_roi_008_右额中回', 'FD_roi_009_左额中回眶部', 'FD_roi_010_右额中回眶部', 'FD_roi_011_左额下回盖部', 'FD_roi_012_右额下回盖部', 'FD_roi_013_左额下回三角部', 'FD_roi_014_右额下回三角部', 'FD_roi_015_左额下回眶部', 'FD_roi_016_右额下回眶部', 'FD_roi_017_左罗兰盖', 'FD_roi_018_右罗兰盖', 'FD_roi_019_左辅助运动区', 'FD_roi_020_右辅助运动区', 'FD_roi_021_左嗅皮层', 'FD_roi_022_右嗅皮层', 'FD_roi_023_左内侧额上回', 'FD_roi_024_右内侧额上回', 'FD_roi_025_左内侧眶额回', 'FD_roi_026_右内侧眶额回', 'FD_roi_027_左直回', 'FD_roi_028_右直回', 'FD_roi_029_左岛叶', 'FD_roi_030_右岛叶', 'FD_roi_031_左扣带回前部', 'FD_roi_032_右扣带回前部', 'FD_roi_033_左扣带回中部', 'FD_roi_034_右扣带回中部', 'FD_roi_035_左扣带回后部', 'FD_roi_036_右扣带回后部', 'FD_roi_037_左海马', 'FD_roi_038_右海马', 'FD_roi_039_左海马旁回', 'FD_roi_040_右海马旁回', 'FD_roi_041_左杏仁核', 'FD_roi_042_右杏仁核', 'FD_roi_043_左距状皮层', 'FD_roi_044_右距状皮层', 'FD_roi_045_左楔叶', 'FD_roi_046_右楔叶', 'FD_roi_047_左舌回', 'FD_roi_048_右舌回', 'FD_roi_049_左枕上回', 'FD_roi_050_右枕上回', 'FD_roi_051_左枕中回', 'FD_roi_052_右枕中回', 'FD_roi_053_左枕下回', 'FD_roi_054_右枕下回', 'FD_roi_055_左梭状回', 'FD_roi_056_右梭状回', 'FD_roi_057_左中央后回', 'FD_roi_058_右中央后回', 'FD_roi_059_左顶上小叶', 'FD_roi_060_右顶上小叶', 'FD_roi_061_左顶下小叶', 'FD_roi_062_右顶下小叶', 'FD_roi_063_左缘上回', 'FD_roi_064_右缘上回', 'FD_roi_065_左角回', 'FD_roi_066_右角回', 'FD_roi_067_左楔前叶', 'FD_roi_068_右楔前叶', 'FD_roi_069_左中央旁小叶', 'FD_roi_070_右中央旁小叶', 'FD_roi_071_左尾状核', 'FD_roi_072_右尾状核', 'FD_roi_073_左壳核', 'FD_roi_074_右壳核', 'FD_roi_075_左苍白球', 'FD_roi_076_右苍白球', 'FD_roi_077_左丘脑', 'FD_roi_078_右丘脑', 'FD_roi_079_左横颞回', 'FD_roi_080_右横颞回', 'FD_roi_081_左颞上回', 'FD_roi_082_右颞上回', 'FD_roi_083_左颞极上部', 'FD_roi_084_右颞极上部', 'FD_roi_085_左颞中回', 'FD_roi_086_右颞中回', 'FD_roi_087_左颞极中部', 'FD_roi_088_右颞极中部', 'FD_roi_089_左颞下回', 'FD_roi_090_右颞下回', 'FD_roi_091_胼胝体', 'FD_roi_092_左侧脑室', 'FD_roi_093_右侧脑室', 'FD_roi_094_左中脑', 'FD_roi_095_右中脑', 'FD_roi_096_左脑桥', 'FD_roi_097_右脑桥', 'FD_roi_098_左延髓', 'FD_roi_099_右延髓', 'FD_roi_100_左小脑', 'FD_roi_101_右小脑', 'FD_roi_102_左小脑蚓部前部', 'FD_roi_103_右小脑蚓部前部', 'FD_roi_104_左小脑蚓部后部', 'FD_roi_105_右小脑蚓部后部', 'FD_roi_106_左小脑蚓部中部', 'FD_roi_107_右小脑蚓部中部', 'FD_roi_108_左丘脑下核', 'FD_roi_109_右丘脑下核', 'FD_roi_110_海马连合', 'FD_roi_111_穹隆', 'FD_roi_120_左白质', 'FD_roi_121_右白质', 'FD_roi_122_左内囊', 'FD_roi_123_右内囊', 'FD_roi_124_脑脊液']
FEATURE_COLS=[c for c in FEATURE_COLS if c!="subject_id"]  # 去掉主键，避免建表列名重复

def build():
    if os.path.exists("data.db"): os.remove("data.db")
    con=sqlite3.connect("data.db"); cur=con.cursor()
    # subjects
    cur.execute("CREATE TABLE subjects(subject_id TEXT, center TEXT, source_batch TEXT, modality TEXT, gestational_age REAL, age_known INTEGER)")
    subs=[]
    for i in range(1,N+1):
        mod=random.choice(MODS)
        sid=f"S{i:04d}_{mod}"                      # 假 id，无姓名
        known=random.random()>0.3
        ga=round(random.uniform(20,40),1) if known else None
        subs.append((sid, random.choice(CENTERS), "synthetic", mod, ga, 1 if known else 0))
    cur.executemany("INSERT INTO subjects VALUES(?,?,?,?,?,?)", subs)
    # brain_features：数值随机；体积/厚度类随孕龄轻微增大，让相关性 Demo 有意义
    q='"'+'","'.join(FEATURE_COLS)+'"'
    ph=",".join(["?"]*(1+len(FEATURE_COLS)))
    cur.execute(f'CREATE TABLE brain_features(subject_id TEXT,{",".join(chr(34)+c+chr(34)+" REAL" for c in FEATURE_COLS)})')
    rows=[]
    for sid,center,_,mod,ga,known in subs:
        g=(ga or 30)/30.0
        vals=[sid]
        for c in FEATURE_COLS:
            if re.search(r"volume|surface_area|thickness|depth", c):
                v=round(random.uniform(0.5,120)*g*random.uniform(0.85,1.15),4)
            elif c.startswith("FD_"):
                v=round(random.uniform(1.8,2.4),4)
            else:
                v=round(random.uniform(-0.05,0.05),6)
            if random.random()<0.01: v=None      # 少量缺失，模拟脏数据
            vals.append(v)
        rows.append(vals)
    cur.executemany(f"INSERT INTO brain_features VALUES({ph})", rows)
    # semantic_dict：由列名派生（脑区术语，非PII）
    cur.execute("CREATE TABLE semantic_dict(field_name TEXT,chinese_term TEXT,unit TEXT,definition TEXT,category TEXT)")
    sem=[("subject_id","个体编号","","唯一标识","维度"),("center","中心/来源","","广州/华西/四川/未标注","维度"),
         ("modality","模态/序列","","haste/trufi/btfe","维度"),("gestational_age","孕龄/孕周","周","部分缺失","维度"),
         ("age_known","孕龄是否已知","0/1","1=有 0=无","维度")]
    core={"cerebrum_left_volume_ml":"左侧大脑体积","cerebrum_right_volume_ml":"右侧大脑体积","cerebellum_left_volume_ml":"左侧小脑体积","cerebellum_right_volume_ml":"右侧小脑体积","lateral_ventricle_left_volume_ml":"左侧侧脑室体积","lateral_ventricle_right_volume_ml":"右侧侧脑室体积","third_ventricle_volume_ml":"第三脑室体积","fourth_ventricle_volume_ml":"第四脑室体积","cortical_thickness_mean_left_mm":"左侧皮层平均厚度","cortical_thickness_mean_right_mm":"右侧皮层平均厚度","cerebrum_volume_hemispheric_asymmetry_index":"大脑体积半球不对称指数"}
    for c in FEATURE_COLS:
        if c in core: sem.append((c,core[c],"ml" if "volume" in c else "","形态学指标","形态学"))
        elif c.startswith("FD_tissue_"): sem.append((c,re.sub(r"^FD_tissue_\\d+_","",c)+"分形维数","","组织级FD","FD-组织"))
        elif c.startswith("FD_roi_"): sem.append((c,re.sub(r"^FD_roi_\\d+_","",c)+"分形维数","","脑区级FD","FD-脑区"))
        else: sem.append((c,c,"","形态学指标","形态学"))
    cur.executemany("INSERT INTO semantic_dict VALUES(?,?,?,?,?)", sem)
    con.commit(); con.close()
    print(f"合成 data.db 完成：subjects {N} 行、brain_features {len(FEATURE_COLS)} 列、semantic_dict {len(sem)} 条（全部假数据，无PII）")

if __name__=="__main__":
    build()
