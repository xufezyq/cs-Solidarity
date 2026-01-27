from wxauto import WeChat
import SteamAuto
from pathlib import Path
import sys

if __name__ == "__main__":
    # 从命令行参数获取配置文件，默认为 config.json
    config_file = sys.argv[1] if len(sys.argv) > 1 else 'config.json'
    
    if not Path(config_file).exists():
        print(f"错误：找不到配置文件 {config_file}")
        print("请先复制 config.json 文件并填写相关配置")
        exit(1)
    
    try:
        steam_auto = SteamAuto.SteamAuto.create_from_config(config_file)
        
        # 显示配置信息
        print("=" * 50)
        print("配置信息：")
        print(f"配置文件: {config_file}")
        print(f"WeChat 群组/个人数量: {len(steam_auto.wechat_groups)}")
        for idx, group in enumerate(steam_auto.wechat_groups, 1):
            print(f"  {idx}. {group}")
        print(f"监听全部好友: {steam_auto.enable_all_friends}")
        if not steam_auto.enable_all_friends:
            print(f"监听的好友数量: {len(steam_auto.monitored_friends)}")
        print("=" * 50)
        
        steam_auto.start()
    except FileNotFoundError as e:
        print(f"配置加载失败: {e}")
        exit(1)
    except Exception as e:
        print(f"发生错误: {e}")
        exit(1)