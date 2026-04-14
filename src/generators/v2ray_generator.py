import base64
from pathlib import Path

def generate_v2ray(configs):
    content = "\n".join(configs[:300])
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    Path("dist").mkdir(exist_ok=True)
    with open("dist/v2ray.txt", "w", encoding="utf-8") as f:
        f.write(encoded)
    print("✅ V2Ray 订阅生成完成 → dist/v2ray.txt")