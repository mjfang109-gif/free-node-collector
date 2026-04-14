import json
import datetime
import qrcode
import base64
import os
import requests
from io import BytesIO
from pathlib import Path
from playwright.sync_api import sync_playwright

# ==========================================
# 全局配置区（优先读取环境变量，无环境变量则使用默认值）
# ==========================================

SUBSCRIPTION_URL="https://raw.githubusercontent.com/mjfang109-gif/free-node-collector/main/dist/top20_clash.yaml"

# 2. 配置节点数据源地址 (填入 json 文件的 Raw 链接)
REMOTE_NODES_URL="https://raw.githubusercontent.com/mjfang109-gif/free-node-collector/main/dist/top_nodes.json"

# ==========================================
# 路径管理：适配 Docker 容器挂载目录 (/app)
# ==========================================
# 获取当前 render.py 所在的目录（在容器内挂载后就是 /app）
ROOT_DIR = Path(__file__).resolve().parent

# 定义 dist 目录直接位于 ROOT_DIR 下
DIST_DIR = ROOT_DIR / 'dist'
DIST_DIR.mkdir(parents=True, exist_ok=True)  # 防御性创建

# 核心文件绝对路径映射（去掉了 .. ，因为都在 /app 下扁平化管理了）
TEMPLATE_PATH = ROOT_DIR / 'live.html'  # 模板在项目根目录
JSON_INPUT_PATH = DIST_DIR / 'top_nodes.json'  # 数据文件在 dist 目录下
TEMP_HTML_PATH = DIST_DIR / 'temp_render.html'  # 临时组装的 HTML 放到 dist 下
OUTPUT_IMAGE_PATH = DIST_DIR / 'bg.jpg'  # 最终截取的推流背景图放到 dist 下


# ==========================================
# 核心函数逻辑
# ==========================================


def download_remote_nodes(url=REMOTE_NODES_URL):
    """备用：从远程拉取节点 JSON（如果你跑的是本地 farmer.py，这个函数不用调用）"""
    print(f"📥 正在从远程拉取节点数据: {url}")
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        with open(JSON_INPUT_PATH, 'wb') as f:
            f.write(response.content)
        print(f"✅ 远程数据已下载至: {JSON_INPUT_PATH}")
    except Exception as e:
        print(f"❌ 下载失败，将尝试使用本地缓存: {e}")


def get_protocol_badge(protocol):
    """协议颜色映射：为不同协议匹配前端的 CSS 类"""
    p = str(protocol).lower().strip()
    if p in ["hy2", "hysteria2", "hysteria"]: return "bg-hy2"
    if p == "vless": return "bg-vless"
    if p == "vmess": return "bg-vmess"
    if p == "trojan": return "bg-trojan"
    if p in ["ss", "shadowsocks"]: return "bg-ss"
    return "bg-default"


def generate_qr_base64(url):
    """纯前端无感知的 Base64 二维码生成"""
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


def update_stream_image():
    # 1. 严格检查数据文件是否存在
    if not JSON_INPUT_PATH.exists():
        print(f"❌ 严重错误: 未找到数据文件 {JSON_INPUT_PATH}")
        print("请确保节点数据文件已正确生成在 dist 目录下！")
        return

    with open(JSON_INPUT_PATH, 'r', encoding='utf-8') as f:
        nodes_data = json.load(f)

    # 2. 组装节点 HTML 行 (只取前 7 个最优节点以防溢出)
    nodes_html_str = ""
    for node in nodes_data[:7]:
        raw_protocol = node.get("protocol", "UNKNOWN")
        badge_class = get_protocol_badge(raw_protocol)

        # 统一格式化显示在画面上的协议名
        display_protocol = raw_protocol.upper()
        if display_protocol in ["HYSTERIA2", "HYSTERIA", "HY2"]:
            display_protocol = "Hy2"
        elif display_protocol == "VLESS":
            display_protocol = "VLess"
        elif display_protocol == "VMESS":
            display_protocol = "VMess"
        elif display_protocol == "TROJAN":
            display_protocol = "Trojan"
        elif display_protocol in ["SS", "SHADOWSOCKS"]:
            display_protocol = "SS"

        # 提取地区信息，并清洗特殊字符
        location = node.get("location", "").strip()
        if not location: location = node.get("name", "").strip()
        if not location: location = node.get("ip", "未知节点")
        location = location.replace("🔒", "🔐").strip()

        latency = node.get("latency_ms", 999)
        ping_class = "ping-good" if latency < 100 else ""

        row_html = f"""
        <div class="node-row">
            <div><span class="badge {badge_class}">{display_protocol}</span></div>
            <div>{location}</div>
            <div class="{ping_class}">{latency} ms</div>
            <div>🟢 极速可用</div>
        </div>
        """
        nodes_html_str += row_html

    # 3. 读取根目录的模板，进行数据替换
    if not TEMPLATE_PATH.exists():
        print(f"❌ 严重错误: 未在根目录找到前端模板 {TEMPLATE_PATH}")
        return

    with open(TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        html_content = f.read()

    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 执行替换占位符
    html_content = html_content.replace('{{nodes_html}}', nodes_html_str)
    html_content = html_content.replace('{{update_time}}', current_time)
    html_content = html_content.replace('{{valid_count}}', str(len(nodes_data)))
    html_content = html_content.replace('{{qr_base64}}', generate_qr_base64(SUBSCRIPTION_URL))

    # 将替换好的 HTML 写入 dist 目录
    with open(TEMP_HTML_PATH, 'w', encoding='utf-8') as f:
        f.write(html_content)

    # 4. 唤起 Playwright 无头浏览器生成推流帧
    print("📸 正在唤起无头浏览器生成推流背景...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # 强制将虚拟相机的尺寸锁定为完美的 1920x1080
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        # 使用 .as_uri() 保证绝对路径在容器环境或多平台下被正确识别为 file:// 协议
        local_url = TEMP_HTML_PATH.as_uri()
        page.goto(local_url)

        # 截屏并保存到 dist/bg.jpg
        page.screenshot(path=str(OUTPUT_IMAGE_PATH), type="jpeg", quality=100)
        browser.close()

    print(f"[{current_time}] 🎉 画面更新成功：{OUTPUT_IMAGE_PATH} 已就绪！")


if __name__ == "__main__":
    update_stream_image()
