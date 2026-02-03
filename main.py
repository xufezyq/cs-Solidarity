import sys
from pathlib import Path
from steam import SteamAuto
from core import init_wechat

if __name__ == "__main__":
    # 从命令行参数获取配置文件，默认为 config.json
    config_file = sys.argv[1] if len(sys.argv) > 1 else 'config.json'
    
    if not Path(config_file).exists():
        print(f"错误：找不到配置文件 {config_file}")
        print("请先复制 config.json 文件并填写相关配置")
        exit(1)
    
    try:
        # 初始化全局WeChat实例
        init_wechat()
        steam_auto = SteamAuto.create_from_config(config_file)
        steam_auto.start()
    except FileNotFoundError as e:
        print(f"配置加载失败: {e}")
        exit(1)
    except Exception as e:
        print(f"发生错误: {e}")
        exit(1)