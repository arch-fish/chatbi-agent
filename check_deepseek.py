"""连通性自测：确认本机能否访问 DeepSeek。跑通打印“✅ 连通”，失败打印原因。"""
from openai import OpenAI
import config
try:
    c = OpenAI(api_key=config.get_api_key(), base_url=config.BASE_URL)
    r = c.chat.completions.create(model=config.MODEL,
        messages=[{"role": "user", "content": "只回复两个字：通了"}], max_tokens=10, temperature=0)
    print("✅ 连通，模型回复：", r.choices[0].message.content)
    print("   用量：", r.usage.prompt_tokens, "in /", r.usage.completion_tokens, "out")
except Exception as e:
    print("❌ 连不上：", type(e).__name__, str(e)[:200])
