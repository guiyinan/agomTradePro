# AgomSAAF Makefile
#
# 常用开发命令快捷方式

.PHONY: help check test lint routes

# 默认目标
help:
	@echo "AgomSAAF 常用命令:"
	@echo ""
	@echo "  check          - 运行所有一致性检查"
	@echo "  test           - 运行所有测试"
	@echo "  lint           - 运行代码风格检查"
	@echo "  routes         - 检查路由一致性"
	@echo "  routes-fix     - 检查路由并显示修复建议"

# 一致性检查
check:
	@echo "运行一致性检查..."
	@python scripts/check_doc_route_sdk_consistency.py --baseline reports/consistency/baseline.json
	@python scripts/check_routes.py

# 路由一致性检查
routes:
	@echo "检查路由一致性..."
	@python scripts/check_routes.py

# 路由检查（带修复建议）
routes-fix:
	@echo "检查路由一致性并显示修复建议..."
	@python scripts/check_routes.py --fix

# 测试
test:
	@echo "运行测试..."
	@python -m pytest

# 代码风格检查
lint:
	@echo "运行代码风格检查..."
	@python -m ruff check .
	@python -m black --check .
	@python -m isort --check-only .
