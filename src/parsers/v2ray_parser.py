import base64

def parse_v2ray_base64(content):
    configs = []
    lines = content.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            # 如果是单行 base64 配置，直接保留；如果是整段 base64，解码后按行分割
            if line.startswith("vmess://") or line.startswith("vless://") or line.startswith("trojan://") or line.startswith("ss://"):
                configs.append(line)
            else:
                decoded = base64.b64decode(line + "==").decode("utf-8", errors="ignore")
                for subline in decoded.splitlines():
                    subline = subline.strip()
                    if subline and (subline.startswith("vmess://") or subline.startswith("vless://")):
                        configs.append(subline)
        except:
            continue
    print(f"从 V2Ray Base64 解析到 {len(configs)} 个节点")
    return configs