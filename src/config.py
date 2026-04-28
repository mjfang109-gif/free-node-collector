import yaml
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# --- 路径配置 ---
_current_file_path = Path(__file__).resolve()
SRC_DIR = _current_file_path.parent
PROJECT_ROOT = SRC_DIR.parent
_config_dir = SRC_DIR / "config"
DIST_DIR = PROJECT_ROOT / "dist"


def load_all_sources():
    """加载所有信源配置文件并合并。"""
    source_files = ["all_type_source.yaml"]
    all_sources = []

    logger.info("🔄 开始加载信源配置文件...")

    for file_name in source_files:
        file_path = _config_dir / file_name
        if not file_path.exists():
            logger.warning(f"⚠️ 信源文件未找到，已跳过：{file_path}")
            continue

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                sources = data.get("sources", [])
                if sources:
                    all_sources.extend(sources)
                    logger.info(f"✅ 成功加载 {len(sources)} 个信源从: {file_name}")
        except Exception as e:
            logger.error(f"❌ 解析信源文件 {file_name} 失败: {e}", exc_info=True)

    if not all_sources:
        logger.critical("❌ 未能加载任何信源，程序无法继续。")

    return all_sources


def get_dist_dir() -> Path:
    """获取输出目录 (dist) 的绝对路径。"""
    return DIST_DIR
