"""供应商切换启动器:双击 启动-自选供应商.bat 进入这里。

按提示粘贴 BASE_URL / API Key / 模型名,即可用任意 OpenAI 兼容端点启动漫游器。
"""
import os

import requests

print("=" * 46)
print(" 关键词漫游器 - 自选供应商启动")
print("=" * 46)
base = input("第1步 粘贴 BASE_URL(例如 https://api.xiaomimimo.com/v1):").strip().rstrip("/")
key = input("第2步 粘贴你的 API Key(sk-开头):").strip()

print("\n第3步 查询该端点可用的模型列表:")
try:
    r = requests.get(base + "/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    for m in r.json().get("data", []):
        print("  -", m["id"])
except Exception as e:
    print(f"  (查询失败:{e} —— 检查 key 和 BASE_URL,或直接去供应商文档抄模型名)")

model = input("\n第4步 从上面列表抄一个模型名粘贴进来:").strip()

os.environ["LLM_BASE_URL"] = base
os.environ["LLM_API_KEY"] = key
os.environ["LLM_MODEL"] = model

port = os.environ.get("ROAM_PORT", "8765")
print(f"\n启动中... 浏览器打开 http://127.0.0.1:{port}  (Ctrl+C 停止服务)\n")

from app import app  # noqa: E402  环境变量已就位,import 时即生效
app.run(host="127.0.0.1", port=port, debug=False)
