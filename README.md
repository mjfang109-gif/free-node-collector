# Free-Node-Collector

全自动免费节点采集器，爬取、筛选、测速，生成最快的代理订阅。

## 功能

- **全网采集**：从 GitHub、Telegram 等公开信源采集
- **精准测速**：clash-speedtest 真实下载速度测试
- **智能筛选**：自动过滤无效节点
- **多协议支持**：VMess、VLESS、Trojan、Shadowsocks、Hysteria2
- **订阅生成**：Clash YAML + V2Ray Base64

## 输出文件

| 文件 | 说明 |
|------|------|
| `top50_clash.yaml` | Top 50 最快节点的 Clash 订阅 |
| `top50_v2ray.txt` | Top 50 最快节点的 V2Ray 订阅 |
| `clash.yaml` | 完整 Clash 配置 |
| `v2ray.txt` | 完整 V2Ray 订阅 |

## 快速开始

### 本地运行

```bash
# 安装依赖
pip install -r requirements.txt
go install github.com/faceair/clash-speedtest@latest

# 运行
python -m src.main
```

### GitHub Actions

每 6 小时自动运行，结果在 `dist/` 目录。

## 配置信源

编辑 `src/config/all_type_source.yaml`:

```yaml
sources:
  - name: 示例信源
    url: https://example.com/sub
    type: clash  # 或 v2ray_base64
```

## 项目结构

```
free-node-collector/
├── .github/workflows/main.yml   # CI/CD
├── src/
│   ├── collectors/              # 采集器
│   ├── parsers/                 # 解析器
│   ├── testers/                 # 测速
│   ├── generators/              # 订阅生成
│   ├── config/                  # 配置文件
│   ├── main.py                  # 主入口
│   └── utils.py                 # 工具函数
├── dist/                        # 输出目录
└── requirements.txt
```
