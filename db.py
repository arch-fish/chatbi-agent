"""数据库层：只读连接 + schema 自省 + 安全执行。"""
import sqlite3
import re

# 为什么要拦截：LLM 生成的 SQL 不可信，万一它生成 DROP TABLE / DELETE，会毁数据。
_BLOCK = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|PRAGMA)\b", re.I)

def get_conn(db_path):
    # mode=ro：只读打开，物理上无法写(纵深防御第二层)。
    # immutable=1：声明该库为静态文件，跳过文件锁与 journal 回滚——
    #   避免旁边残留 *-journal 时误报 "attempt to write a readonly database"。
    #   适用前提：查询期间库不会被改动(我们正是这种只读分析场景)。
    return sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)

def get_schema(db_path):
    """返回每张表的列名，用于喂给 LLM——它不看库就不知道有哪些表和列。"""
    con = get_conn(db_path); cur = con.cursor()
    schema = {}
    for t in ("subjects", "brain_features", "semantic_dict"):
        schema[t] = [r[1] for r in cur.execute(f"PRAGMA table_info({t})")]
    con.close()
    return schema

def run_sql(db_path, sql):
    """执行只读查询，返回(列名, 数据行)。非 SELECT 直接拒绝。"""
    if _BLOCK.search(sql):
        raise ValueError("安全拦截：只允许 SELECT 查询")
    con = get_conn(db_path); cur = con.cursor()
    try:
        cur.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
    finally:
        con.close()
    return cols, rows
