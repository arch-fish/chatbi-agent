"""交互式命令行：循环输入中文问题，看 SQL 和结果。用于自测和面试 demo。"""
from nl2sql import ask

def main():
    print("胎儿脑数据 ChatBI（基线版）。输入中文问题，quit 退出。\n")
    while True:
        try:
            q = input("问> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q in ("quit", "exit", "q", ""):
            break
        ask(q)
        print()

if __name__ == "__main__":
    main()
