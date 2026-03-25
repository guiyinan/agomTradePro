from django.core.management.base import BaseCommand
from apps.pulse.infrastructure.models import PulseWeightConfig, PulseIndicatorWeight

class Command(BaseCommand):
    help = "设置特定指标的权重"

    def add_arguments(self, parser):
        parser.add_argument("--indicator", type=str, required=True, help="指标代码")
        parser.add_argument("--weight", type=float, required=True, help="权重值")

    def handle(self, *args, **options):
        indicator_code = options["indicator"]
        weight = options["weight"]

        active_config = PulseWeightConfig.objects.filter(is_active=True).first()
        if not active_config:
            self.stdout.write(self.style.ERROR("没有找到激活的 PulseWeightConfig"))
            return

        indicator_weight = PulseIndicatorWeight.objects.filter(
            config=active_config, indicator_code=indicator_code
        ).first()

        if indicator_weight:
            indicator_weight.weight = weight
            indicator_weight.save()
            self.stdout.write(self.style.SUCCESS(f"已将 {indicator_code} 权重更新为 {weight}"))
        else:
            self.stdout.write(self.style.ERROR(f"未在配置中找到指标 {indicator_code}"))
