"""
版本管理模块 - 基于 Git 提交次数自动生成版本号
"""
import subprocess
from pathlib import Path


def get_version():
    """
    获取自动生成的版本号
    格式: 1.0.{commit_count}-{short_hash}
    示例: 1.0.42-a1b2c3d
    """
    try:
        # 获取 Git 提交次数
        commit_count = subprocess.check_output(
            ['git', 'rev-list', '--count', 'HEAD'],
            cwd=Path(__file__).parent,
            stderr=subprocess.DEVNULL
        ).decode().strip()
        
        # 获取短哈希 (7位)
        short_hash = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=Path(__file__).parent,
            stderr=subprocess.DEVNULL
        ).decode().strip()
        
        return f"2.4.{commit_count}-{short_hash}"
    except Exception:
        # 如果获取失败，返回默认版本
        return "2.4.0-dev"


def get_version_info():
    """
    获取详细的版本信息
    """
    try:
        # 获取完整提交哈希
        full_hash = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'],
            cwd=Path(__file__).parent,
            stderr=subprocess.DEVNULL
        ).decode().strip()
        
        # 获取提交日期
        commit_date = subprocess.check_output(
            ['git', 'log', '-1', '--format=%cd', '--date=iso'],
            cwd=Path(__file__).parent,
            stderr=subprocess.DEVNULL
        ).decode().strip()
        
        # 获取提交信息
        commit_message = subprocess.check_output(
            ['git', 'log', '-1', '--format=%s'],
            cwd=Path(__file__).parent,
            stderr=subprocess.DEVNULL
        ).decode().strip()
        
        # 获取分支名
        branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=Path(__file__).parent,
            stderr=subprocess.DEVNULL
        ).decode().strip()
        
        return {
            'version': get_version(),
            'full_hash': full_hash,
            'commit_date': commit_date,
            'commit_message': commit_message,
            'branch': branch
        }
    except Exception:
        return {
            'version': '1.0.0-dev',
            'full_hash': 'unknown',
            'commit_date': 'unknown',
            'commit_message': 'unknown',
            'branch': 'unknown'
        }


# 全局版本号
VERSION = get_version()

if __name__ == '__main__':
    # 测试输出
    print(f"版本号: {get_version()}")
    print("\n详细信息:")
    for key, value in get_version_info().items():
        print(f"  {key}: {value}")
