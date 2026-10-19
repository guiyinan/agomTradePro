# ASH03 bounded OpenAPI static review

## Scope and exact artifacts

I reviewed `.tmp/ash03-openapi-bounded-185/` without project imports, tests, ORM/database, QA, network, Git, or shared writes. The packet's raw SHA-256 values are:

| Artifact | SHA-256 |
|---|---|
| `manifest.json` | `b454d519994c61270eb75874ee2d93ace4662b168aaae68768c577f8fdebd7d3` |
| `build_bounded_projection.py` | `469453654c1f6f2e94c992628c07b1821be6f6ae896400145dfb468a51c08f15` |
| candidate YAML (`schema.yml`, `openapi.yaml`) | `bccd71ade8dc82576faa2e9314b82621422d3e70fe8eb3f5d4cb38218a6d0707` |
| candidate `openapi.json` | `b783d5b42b8c07e32f6e8557499bc8e1c1d7c66b049ec1846723e16ffaeac16d` |
| `README.md` | `c42d58944224020b639ed460002e51a391b5db6b859ba4a9297702c4120cd20f` |

The captured BASE hashes match `manifest.json`; all three candidate hashes and byte counts match the manifest. At review time the three shared OpenAPI files were byte-identical to these candidate postimages.

Current interface source hashes:

| Path | SHA-256 |
|---|---|
| `apps/simulated_trading/interface/serializers.py` | `ce573ea271f4ac2bc3a5fc47b52f7a85e41df52686a9c667e3993fe3e028069f` |
| `apps/simulated_trading/interface/views.py` | `aa05a63cad26ce9903e0899f2e6d970d8da30f116f1d76f40ece46064060d786` |
| `apps/simulated_trading/application/auto_trading_outcome_reporting.py` | `26e6dade8e46da6fcb1012d130bb1b75850c690810226b21f45d22358cdd63de` |
| `apps/simulated_trading/domain/auto_trading_outcomes.py` | `2630cc0969f0d3475c068a7948bc1165064c9415d978d75f0a23f9d6c2ca2dc7` |

## Bounded projection disposition

Independent pure parsing confirmed that candidate `schema.yml`, `openapi.yaml`, and `openapi.json` are semantically identical. The selected `/api/simulated-trading/auto-trading/run/` operation and all seven selected schemas exactly match the full-generated source. All unselected paths, schemas, component sections, and top-level values exactly match BASE. The selected reference closure resolves, and no other BASE path/component references these selected schema names. The candidate therefore makes the declared bounded projection and does not carry unrelated full-generated drift.

The request and response properties match the current serializers: optional `trade_date` with `format: date`; optional `account_ids` integer array with the 10,000-item cap; five normalized outcomes; `blocked`/`failed` issue kinds; account and aggregate trade counts; nullable `stored` values; nullable account reason; and optional nullable response `error`. The current payload builder emits those batch/account fields, summary, units, trade date, and stable error code. The request body fields are optional as in the serializer. The required `Idempotency-Key` header, body formats, and response references are present and resolve.

## P2 contract gaps

1. The OpenAPI parameter for required `Idempotency-Key` has only `schema: {type: string}`. The actual `ManualTradeIdempotencyKeySerializer` enforces nonempty input, maximum length 128, and no whitespace; the prose description mentions the length and whitespace rules, but the machine-readable schema lacks `minLength`, `maxLength`, and a whitespace pattern. Generated clients can therefore accept keys that the API rejects. The bounded packet faithfully copies the current `typed_extend_schema` declaration, which manually specifies only a string type. The minimal correction belongs in that parameter declaration, followed by regeneration of the same bounded closure.

2. The operation documents only 200, 400, and 409, but `AutoTradingAPIView.post` has a concrete 500 path at `apps/simulated_trading/interface/views.py:774-784`, returning `{success: false, error, stable_error_code}` when engine setup fails. That response is neither listed nor represented by `AutoTradingRunResponseSerializer`, whose success-result fields are required. The decorator at `views.py:714-728` needs a dedicated setup-failure response schema and 500 entry before regenerated OpenAPI can describe the runtime contract accurately.

These are documentation-contract P2s in the selected operation, not behavioral defects introduced by this projection. No P1 was found. No OpenAPI packet files were changed by this review.