"""集中配置。为什么单独一个文件：换模型/换厂商只改这里，代码其他部分不动。"""
import os

# 为什么用 OpenAI SDK + base_url：DeepSeek 兼容 OpenAI 协议。
# 好处——以后想换成别的厂商(通义/Kimi/本地模型)，只改 BASE_URL 和 MODEL，业务代码零改动。
BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-v4-flash"   # 注意：deepseek-chat 将于 2026-07-24 弃用，故用 v4-flash

# 为什么 key 从环境/.env 读、不写进代码：项目要开源，硬编码 key = 泄露。
def get_api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        # 从同目录 .env 兜底读取（避免用户忘了 export）
        env = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env):
            for line in open(env, encoding="utf-8"):
                if line.startswith("DEEPSEEK_API_KEY="):
                    key = line.split("=", 1)[1].strip()
    if not key:
        raise RuntimeError("未找到 DEEPSEEK_API_KEY，请在 .env 或环境变量中设置")
    return key

import os as _os
DB_PATH = _os.path.join(_os.path.dirname(__file__), "data.db")


def get_lab_password() -> str:
    """内部工具访问口令。从环境/.env 读 LAB_PASSWORD，缺省 changeme（请务必改掉）。"""
    pw = _os.environ.get("LAB_PASSWORD", "")
    if not pw:
        env = _os.path.join(_os.path.dirname(__file__), ".env")
        if _os.path.exists(env):
            for line in open(env, encoding="utf-8"):
                if line.startswith("LAB_PASSWORD="):
                    pw = line.split("=", 1)[1].strip()
    return pw or "changeme"
