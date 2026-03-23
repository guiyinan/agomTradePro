"""
AgomTradePro Version Information.

版本号管理 - 单一来源（Single Source of Truth）
"""

__version__ = "0.7.0"
__build__ = "20260323"
__codename__ = "AgomTradePro"


def get_version() -> str:
    """获取版本号"""
    return __version__


def get_build() -> str:
    """获取构建日期"""
    return __build__


def get_full_version() -> str:
    """获取完整版本号（含 build 日期）"""
    return f"{__version__}-build.{__build__}"


def get_version_info() -> dict:
    """获取完整版本信息"""
    return {
        "version": __version__,
        "build": __build__,
        "codename": __codename__,
        "full_version": get_full_version(),
    }
