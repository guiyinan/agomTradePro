from django.core.management.base import BaseCommand

from apps.pulse.infrastructure.data_provider import DEFAULT_PULSE_INDICATORS
from apps.pulse.infrastructure.models import PulseWeightConfig, PulseIndicatorWeight

class Command(BaseCommand):
    help = "初始化 Pulse 权重配置"

    def handle(self, *args, **options):
        # 1. 创建整体配置
        config, created = PulseWeightConfig.objects.get_or_create(
            name="Phase 3 默认权重配置",
        )
        if created:
            self.stdout.write(self.style.SUCCESS('创建新的 PulseWeightConfig'))
        else:
            self.stdout.write('PulseWeightConfig 已存在')
        
        # 将其设置为唯一的激活配置
        PulseWeightConfig.objects.exclude(id=config.id).update(is_active=False)
        config.is_active = True
        config.save()

        # 2. 从 Phase 3 推荐构建维度内指标权重（等权处理维度内各项，维度总分通过 PulseConfig 处理）
        # 这里只将指标配置进去。指标权重默认=1.0。
        for indicator in DEFAULT_PULSE_INDICATORS:
            PulseIndicatorWeight.objects.get_or_create(
                config=config,
                indicator_code=indicator.code,
                defaults={
                    "dimension": indicator.dimension,
                    "weight": 1.0,
                    "is_enabled": True,
                }
            )

        self.stdout.write(self.style.SUCCESS("初始化完成。指标权重已同步。"))
