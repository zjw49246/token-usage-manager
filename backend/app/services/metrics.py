"""Prometheus 指标（P21）：请求数 / token / 成本 / 延迟，供 /metrics 抓取。"""
from prometheus_client import Counter, Histogram

REQUESTS = Counter("tr_requests_total", "代理请求总数", ["model", "provider", "status", "cached"])
TOKENS = Counter("tr_tokens_total", "token 总量", ["model", "type"])
COST = Counter("tr_cost_usd_total", "累计成本(USD)", ["model"])
LATENCY = Histogram("tr_request_latency_seconds", "请求延迟(秒)", ["model"],
                    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60))


def observe(*, model: str, provider: str | None, status: str, cached: bool,
            input_tokens, output_tokens, cost_usd, duration_ms) -> None:
    try:
        REQUESTS.labels(model=model, provider=provider or "-", status=status, cached=str(cached).lower()).inc()
        if input_tokens:
            TOKENS.labels(model=model, type="prompt").inc(input_tokens)
        if output_tokens:
            TOKENS.labels(model=model, type="completion").inc(output_tokens)
        if cost_usd:
            COST.labels(model=model).inc(cost_usd)
        if duration_ms:
            LATENCY.labels(model=model).observe(duration_ms / 1000.0)
    except Exception:
        pass  # 指标不影响主流程
