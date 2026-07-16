"""批量跑测试题：一条命令看基线版在每道题上生成的SQL和结果/报错。
用途：①自测基线短板 ②这些答错的题就是评估集的种子。"""
from nl2sql import ask

def main():
    qs = [l.strip() for l in open("questions.txt", encoding="utf-8")
          if l.strip() and not l.startswith("#")]
    for i, q in enumerate(qs, 1):
        print("=" * 70)
        print(f"[{i}] 问：{q}")
        try:
            r = ask(q, verbose=False)
            print("SQL:", r["sql"])
            if r.get("error"):
                print("❌ 执行报错:", r["error"])
            else:
                print("结果:", r["cols"])
                for row in r["rows"][:8]:
                    print("   ", row)
                if len(r["rows"]) > 8:
                    print(f"    ...(共{len(r['rows'])}行)")
        except Exception as e:
            print("❌ 调用异常:", type(e).__name__, str(e)[:150])
        print()

if __name__ == "__main__":
    main()
