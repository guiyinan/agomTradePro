"""
下载第三方 JavaScript/CSS 库到本地 vendor 目录
"""
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

# 设置 UTF-8 编码输出
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
VENDOR_DIR = PROJECT_ROOT / 'core' / 'static' / 'vendor'

# 创建目录
(VENDOR_DIR / 'js').mkdir(parents=True, exist_ok=True)
(VENDOR_DIR / 'css').mkdir(parents=True, exist_ok=True)

# 要下载的文件
LIBS = {
    # JavaScript 库
    'js/htmx.min.js': {
        'url': 'https://unpkg.com/htmx.org@1.9.10/dist/htmx.min.js',
        'backup': 'https://cdn.jsdelivr.net/npm/htmx.org@1.9.10/dist/htmx.min.js',
    },
    'js/alpine.min.js': {
        'url': 'https://cdn.jsdelivr.net/npm/alpinejs@3.13.5/dist/cdn.min.js',
        'backup': 'https://unpkg.com/alpinejs@3.13.5/dist/cdn.min.js',
    },
    'js/flatpickr.min.js': {
        'url': 'https://unpkg.com/flatpickr@4.6.13/dist/flatpickr.min.js',
        'backup': 'https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/flatpickr.min.js',
    },
    'js/flatpickr.zh.js': {
        'url': 'https://unpkg.com/flatpickr@4.6.13/dist/l10n/zh.js',
        'backup': 'https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/l10n/zh.js',
    },
    'js/sweetalert2.all.min.js': {
        'url': 'https://cdn.jsdelivr.net/npm/sweetalert2@11.10.3/dist/sweetalert2.all.min.js',
        'backup': 'https://unpkg.com/sweetalert2@11.10.3/dist/sweetalert2.all.min.js',
    },
    'js/echarts.min.js': {
        'url': 'https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js',
        'backup': 'https://unpkg.com/echarts@5.4.3/dist/echarts.min.js',
    },

    # CSS 库
    'css/bootstrap-icons.css': {
        'url': 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css',
        'backup': 'https://unpkg.com/bootstrap-icons@1.11.3/font/bootstrap-icons.css',
    },
    'css/flatpickr.min.css': {
        'url': 'https://unpkg.com/flatpickr@4.6.13/dist/flatpickr.min.css',
        'backup': 'https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/flatpickr.min.css',
    },
}

# Bootstrap Icons 字体文件（需要额外处理）
BOOTSTRAP_ICONS_FONTS = {
    'fonts/bootstrap-icons.woff': 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff',
    'fonts/bootstrap-icons.woff2': 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff2',
}


def download_file(url: str, dest_path: Path, backup_url: str = None) -> bool:
    """下载文件到本地"""
    # 如果文件已存在，跳过
    if dest_path.exists():
        print(f'Skip (exists): {dest_path.name}')
        return True

    urls_to_try = [url]
    if backup_url:
        urls_to_try.append(backup_url)

    for download_url in urls_to_try:
        try:
            print(f'Downloading: {download_url}')
            print(f'  -> {dest_path}')

            # 添加超时和用户代理
            request = urllib.request.Request(
                download_url,
                headers={'User-Agent': 'Mozilla/5.0'}
            )

            with urllib.request.urlopen(request, timeout=30) as response:
                with open(dest_path, 'wb') as f:
                    f.write(response.read())

            # 计算文件大小
            size = dest_path.stat().st_size
            size_kb = size / 1024

            print(f'  [OK] ({size_kb:.1f} KB)')
            return True
        except Exception as e:
            print(f'  [FAIL] {e}')
            if download_url != urls_to_try[-1]:
                print('  Trying backup source...')
            continue

    return False


def process_bootstrap_icons_css():
    """修复 Bootstrap Icons CSS 中的字体路径"""
    css_file = VENDOR_DIR / 'css' / 'bootstrap-icons.css'

    if not css_file.exists():
        return

    content = css_file.read_text(encoding='utf-8')

    # 替换字体文件路径
    # 原路径: url("./fonts/bootstrap-icons.woff2?")
    # 新路径: url("{% static 'vendor/fonts/bootstrap-icons.woff2' %}")
    content = content.replace(
        'url("./fonts/',
        'url("{% static \'vendor/fonts/'
    )

    css_file.write_text(content, encoding='utf-8')
    print('  [OK] Bootstrap Icons CSS fixed')


def main():
    print('=' * 60)
    print('AgomTradePro - Vendor Libraries Download')
    print('=' * 60)
    print()

    success_count = 0
    total_count = len(LIBS)

    # 下载主要文件
    for rel_path, info in LIBS.items():
        dest_path = VENDOR_DIR / rel_path
        backup_url = info.get('backup')
        if download_file(info['url'], dest_path, backup_url):
            success_count += 1
        print()

    # 下载 Bootstrap Icons 字体
    print('Downloading Bootstrap Icons fonts...')
    font_dir = VENDOR_DIR / 'fonts'
    font_dir.mkdir(exist_ok=True)

    font_success = 0
    for name, url in BOOTSTRAP_ICONS_FONTS.items():
        dest_path = font_dir / Path(name).name
        if download_file(url, dest_path):
            font_success += 1
        print()

    if font_success > 0:
        process_bootstrap_icons_css()

    print('=' * 60)
    print(f'Done: {success_count}/{total_count} main files')
    print(f'Fonts: {font_success}/{len(BOOTSTRAP_ICONS_FONTS)} files')
    print('=' * 60)
    print()
    print(f'All files downloaded to: {VENDOR_DIR}')
    print()
    print('Next: Update template references')


if __name__ == '__main__':
    main()
