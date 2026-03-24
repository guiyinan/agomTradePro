from django.core.management.base import BaseCommand
from apps.pulse.infrastructure.models import PulseWeightConfig

class Command(BaseCommand):
    help = "查看当前 Pulse 权重配置"

    def handle(self, *args, **options):
        active_config = PulseWeightConfig.objects.filter(is_active=True).first()
        if not active_config:
            self.stdout.write(self.style.WARNING("没有找到激活的 PulseWeightConfig"))
            return

        self.stdout.write(self.style.SUCCESS(f"当前激活配置: {active_config.name}"))
        for w in active_config.weights.filter(is_enabled=True):
            self.stdout.write(f" [{w.dimension}] {w.indicator_code} = {w.weight}")
