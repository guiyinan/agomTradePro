# -*- coding: utf-8 -*-
"""
Migration: Create Regime threshold configuration model

创建 Regime 判定阈值配置表，使阈值可动态调整而非硬编码。
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('regime', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='RegimeThresholdConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=100, verbose_name='配置名称')),
                ('is_active', models.BooleanField(default=True, verbose_name='是否激活')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
            ],
            options={
                'verbose_name': 'Regime阈值配置',
                'verbose_name_plural': 'Regime阈值配置',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='RegimeIndicatorThreshold',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('config', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='thresholds', to='regime.regimethresholdconfig', verbose_name='配置')),
                ('indicator_code', models.CharField(max_length=50, verbose_name='指标代码')),
                ('indicator_name', models.CharField(max_length=100, verbose_name='指标名称')),
                ('level_low', models.FloatField(help_text='低水平阈值（如 PMI < 50 为收缩）', verbose_name='低水平阈值')),
                ('level_high', models.FloatField(help_text='高水平阈值（如 PMI > 50 为扩张）', verbose_name='高水平阈值')),
                ('description', models.TextField(blank=True, verbose_name='说明')),
            ],
            options={
                'verbose_name': '指标阈值',
                'verbose_name_plural': '指标阈值',
            },
        ),
        migrations.CreateModel(
            name='RegimeTrendIndicator',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('config', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='trend_indicators', to='regime.regimethresholdconfig', verbose_name='配置')),
                ('indicator_code', models.CharField(max_length=50, verbose_name='指标代码')),
                ('momentum_period', models.IntegerField(default=3, help_text='动量计算周期（月）', verbose_name='动量周期')),
                ('trend_weight', models.FloatField(default=0.3, help_text='趋势权重（0-1），用于调整 Regime 判定', verbose_name='趋势权重')),
            ],
            options={
                'verbose_name': '趋势指标',
                'verbose_name_plural': '趋势指标',
            },
        ),
    ]
