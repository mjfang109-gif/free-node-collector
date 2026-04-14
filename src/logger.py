import logging
import logging.config
import yaml
from pathlib import Path

def setup_logger():
    """
    从 YAML 配置文件加载日志配置并应用。
    """
    project_root = Path(__file__).parent.parent.resolve()
    config_path = project_root / "src" / "config" / "logging.yaml"
    logs_dir = project_root / "logs"
    
    logs_dir.mkdir(exist_ok=True)

    if not config_path.exists():
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
        logging.warning(f"日志配置文件未找到: {config_path}。已启用基础日志配置。")
        return logging.getLogger()

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # 修正：将文件名和目录拼接成绝对路径
        if 'handlers' in config and 'file' in config['handlers']:
            filename = config['handlers']['file'].get('filename')
            if filename:
                # 确保 filename 是绝对路径
                config['handlers']['file']['filename'] = logs_dir / filename
        
        logging.config.dictConfig(config)
        
    except Exception as e:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
        logging.critical(f"加载日志配置失败: {e}。已启用基础日志配置。", exc_info=True)

    return logging.getLogger()
