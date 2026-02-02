-- USD 数据迁移 SQL
-- 生成时间: 2026-01-31 22:39:40.704528
-- 汇率: 7.2 USD/CNY
-- 记录数: 58

BEGIN;

-- 设置时区
SET TIME ZONE 'Asia/Shanghai';

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23075956799999.996,
    '2021-02-01',
    '2021-02-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.360458',
    '2026-01-02 01:34:11.360475',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    22824208800000.0,
    '2021-03-01',
    '2021-03-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.403464',
    '2026-01-02 01:34:11.403482',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23026896000000.0,
    '2021-04-01',
    '2021-04-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.404264',
    '2026-01-02 01:34:11.404274',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23196981600000.0,
    '2021-05-01',
    '2021-05-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.405011',
    '2026-01-02 01:34:11.405020',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23140872000000.0,
    '2021-06-01',
    '2021-06-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.406058',
    '2026-01-02 01:34:11.406069',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23298408000000.0,
    '2021-07-01',
    '2021-07-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.406868',
    '2026-01-02 01:34:11.406878',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23271235200000.0,
    '2021-08-01',
    '2021-08-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.407680',
    '2026-01-02 01:34:11.407690',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23044507199999.996,
    '2021-09-01',
    '2021-09-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.408410',
    '2026-01-02 01:34:11.408420',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23166820799999.996,
    '2021-10-01',
    '2021-10-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.409134',
    '2026-01-02 01:34:11.409144',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23201179200000.0,
    '2021-11-01',
    '2021-11-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.409979',
    '2026-01-02 01:34:11.409989',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23401195200000.0,
    '2021-12-01',
    '2021-12-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.410939',
    '2026-01-02 01:34:11.410957',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23195750400000.0,
    '2022-01-01',
    '2022-01-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.412047',
    '2026-01-02 01:34:11.412103',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23139554400000.0,
    '2022-02-01',
    '2022-02-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.413040',
    '2026-01-02 01:34:11.413050',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    22953556800000.0,
    '2022-03-01',
    '2022-03-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.413907',
    '2026-01-02 01:34:11.413916',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    22461984000000.0,
    '2022-04-01',
    '2022-04-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.414727',
    '2026-01-02 01:34:11.414737',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    22520016000000.0,
    '2022-05-01',
    '2022-05-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.415462',
    '2026-01-02 01:34:11.415471',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    22113158400000.0,
    '2022-06-01',
    '2022-06-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.416206',
    '2026-01-02 01:34:11.416222',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    22349311200000.0,
    '2022-07-01',
    '2022-07-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.416969',
    '2026-01-02 01:34:11.416978',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    21995143200000.0,
    '2022-08-01',
    '2022-08-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.417690',
    '2026-01-02 01:34:11.417699',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    21808476000000.0,
    '2022-09-01',
    '2022-09-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.418397',
    '2026-01-02 01:34:11.418406',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    21977474400000.0,
    '2022-10-01',
    '2022-10-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.419132',
    '2026-01-02 01:34:11.419142',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    22445913600000.004,
    '2022-11-01',
    '2022-11-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.419911',
    '2026-01-02 01:34:11.419920',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    22519375200000.0,
    '2022-12-01',
    '2022-12-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.420638',
    '2026-01-02 01:34:11.420647',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    22928126400000.0,
    '2023-01-01',
    '2023-01-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.421446',
    '2026-01-02 01:34:11.421455',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    22558701600000.0,
    '2023-02-01',
    '2023-02-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.422244',
    '2026-01-02 01:34:11.422253',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    22923878400000.0,
    '2023-03-01',
    '2023-03-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.422980',
    '2026-01-02 01:34:11.422989',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23074315200000.0,
    '2023-04-01',
    '2023-04-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.423702',
    '2026-01-02 01:34:11.423711',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    22870857600000.0,
    '2023-05-01',
    '2023-05-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.424420',
    '2026-01-02 01:34:11.424429',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    22989585600000.0,
    '2023-06-01',
    '2023-06-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.425146',
    '2026-01-02 01:34:11.425155',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23070744000000.0,
    '2023-07-01',
    '2023-07-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.425947',
    '2026-01-02 01:34:11.425956',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    22752705600000.0,
    '2023-08-01',
    '2023-08-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.427371',
    '2026-01-02 01:34:11.427403',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    22428504000000.0,
    '2023-09-01',
    '2023-09-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.428486',
    '2026-01-02 01:34:11.428496',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    22328812800000.0,
    '2023-10-01',
    '2023-10-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.429340',
    '2026-01-02 01:34:11.429349',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    22837010400000.0,
    '2023-11-01',
    '2023-11-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.430256',
    '2026-01-02 01:34:11.430266',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23313434400000.0,
    '2023-12-01',
    '2023-12-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.431074',
    '2026-01-02 01:34:11.431084',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23179104000000.0,
    '2024-01-01',
    '2024-01-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.431869',
    '2026-01-02 01:34:11.431879',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23225882399999.996,
    '2024-02-01',
    '2024-02-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.432635',
    '2026-01-02 01:34:11.432645',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23368730400000.0,
    '2024-03-01',
    '2024-03-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.433372',
    '2026-01-02 01:34:11.433381',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23045983200000.0,
    '2024-04-01',
    '2024-04-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.434179',
    '2026-01-02 01:34:11.434194',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23270680800000.0,
    '2024-05-01',
    '2024-05-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.434978',
    '2026-01-02 01:34:11.434988',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23200977600000.004,
    '2024-06-01',
    '2024-06-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.435804',
    '2026-01-02 01:34:11.435814',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23445878400000.004,
    '2024-07-01',
    '2024-07-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.436530',
    '2026-01-02 01:34:11.436540',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23675148000000.0,
    '2024-08-01',
    '2024-08-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.437465',
    '2026-01-02 01:34:11.437475',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23877842399999.996,
    '2024-09-01',
    '2024-09-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.438261',
    '2026-01-02 01:34:11.438271',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23479560000000.0,
    '2024-10-01',
    '2024-10-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.439038',
    '2026-01-02 01:34:11.439047',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23514192000000.0,
    '2024-11-01',
    '2024-11-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.439854',
    '2026-01-02 01:34:11.439864',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23056970400000.0,
    '2024-12-01',
    '2024-12-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.440568',
    '2026-01-02 01:34:11.440595',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23105059200000.0,
    '2025-01-01',
    '2025-01-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.441384',
    '2026-01-02 01:34:11.441393',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23236012800000.0,
    '2025-02-01',
    '2025-02-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.442188',
    '2026-01-02 01:34:11.442197',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23332788000000.004,
    '2025-03-01',
    '2025-03-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.443882',
    '2026-01-02 01:34:11.443893',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23627966400000.004,
    '2025-04-01',
    '2025-04-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.444690',
    '2026-01-02 01:34:11.444700',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23653836000000.004,
    '2025-05-01',
    '2025-05-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.445510',
    '2026-01-02 01:34:11.445519',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23885438400000.0,
    '2025-06-01',
    '2025-06-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.446323',
    '2026-01-02 01:34:11.446332',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23704092000000.0,
    '2025-07-01',
    '2025-07-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.447067',
    '2026-01-02 01:34:11.447076',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    23919508800000.004,
    '2025-08-01',
    '2025-08-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.447916',
    '2026-01-02 01:34:11.447926',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    24038337600000.0,
    '2025-09-01',
    '2025-09-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.448770',
    '2026-01-02 01:34:11.448780',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    24072069600000.0,
    '2025-10-01',
    '2025-10-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.449521',
    '2026-01-02 01:34:11.449530',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();

INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    'CN_FX_RESERVES',
    24093878400000.0,
    '2025-11-01',
    '2025-11-11',
    0,
    'akshare',
    1,
    '2026-01-02 01:34:11.450286',
    '2026-01-02 01:34:11.450295',
    'M',
    '元',
    '万亿美元'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();


COMMIT;
