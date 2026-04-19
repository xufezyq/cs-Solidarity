"""
disaster_warning 实例重导出模块
实际代码位于 Plugins/disaster_warning/
"""

import sys
import importlib.util
from pathlib import Path

# 添加 Plugins 到 sys.path
_plugins_path = Path(__file__).parent.parent / "Plugins"
if str(_plugins_path) not in sys.path:
    sys.path.insert(0, str(_plugins_path))

# 手动加载 disaster_warning 包，确保它被正确注册到 sys.modules
_dw_spec = importlib.util.find_spec('disaster_warning')
if _dw_spec and 'disaster_warning' not in sys.modules:
    _dw_module = importlib.util.module_from_spec(_dw_spec)
    sys.modules['disaster_warning'] = _dw_module
    _dw_spec.loader.exec_module(_dw_module)

# 现在可以正常导入子模块
from disaster_warning.disaster_instance import DisasterWarningInstance

__all__ = ["DisasterWarningInstance"]
