"""PriceAgent for A-share market — price, turnover, limit board signals via rqdatac."""

from typing import Any, Optional
import os
from datetime import datetime

from backend.agents.base_agent import BaseFinancialAgent, AgentOutput, EvidenceItem
from backend.services.circuit_breaker import CircuitBreaker


class AllSourcesFailedError(Exception):
    pass


class PriceAgent(BaseFinancialAgent):
    AGENT_NAME = "PriceAgent"
    CACHE_TTL = 30
    MAX_REFLECTIONS = 1

    def __init__(self, llm, cache, tools_module, circuit_breaker: Optional[CircuitBreaker] = None):
        if circuit_breaker is None:
            circuit_breaker = CircuitBreaker(
                failure_threshold=int(os.getenv("PRICE_CB_FAILURE_THRESHOLD", "3")),
                recovery_timeout=float(os.getenv("PRICE_CB_RECOVERY_TIMEOUT", "60")),
                half_open_success_threshold=int(os.getenv("PRICE_CB_HALF_OPEN_SUCCESS", "1")),
            )
        super().__init__(llm, cache, circuit_breaker)
        self.tools = tools_module

    def _get_tool_registry(self) -> dict:
        """PriceAgent tool registry: quote + A-share specific signals."""
        registry = {}
        tools = self.tools
        if not tools:
            return registry

        search_fn = getattr(tools, "search", None)
        if search_fn:
            registry["search"] = {
                "func": search_fn,
                "description": "搜索A股价格补充信息（波动、催化事件、板块异动）",
                "call_with": "query",
            }

        turnover_fn = getattr(tools, "get_turnover_rate", None)
        if turnover_fn:
            registry["get_turnover_rate"] = {
                "func": turnover_fn,
                "description": "获取A股换手率数据（反映交易活跃度）",
                "call_with": "ticker",
            }

        suspension_fn = getattr(tools, "get_suspension_info", None)
        if suspension_fn:
            registry["get_suspension_info"] = {
                "func": suspension_fn,
                "description": "查询A股停牌/复牌状态",
                "call_with": "ticker",
            }
        return registry

    async def _initial_search(self, query: str, ticker: str) -> Any:
        del query
        cache_key = f"{ticker}:price:realtime"

        cached = self.cache.get(cache_key)
        if cached:
            return cached

        sources = ["rqdatac", "eastmoney", "search"]
        last_error = None

        for source in sources:
            if self.circuit_breaker.can_call(source):
                try:
                    result = await self._fetch_from_source(source, ticker)
                    if result:
                        self.circuit_breaker.record_success(source)
                        self.cache.set(cache_key, result, self.CACHE_TTL)
                        return result
                except Exception as e:
                    last_error = e
                    self.circuit_breaker.record_failure(source)

        try:
            fallback_result = await self._fetch_from_source("search", ticker)
            if fallback_result:
                return fallback_result
        except Exception:
            pass

        raise AllSourcesFailedError(f"所有数据源均失败: {ticker}. Last error: {last_error}")

    async def _fetch_from_source(self, source: str, ticker: str) -> Any:
        tools = self.tools
        tool_func = None
        if source == "rqdatac":
            tool_func = getattr(tools, "get_stock_price", None)
        elif source == "eastmoney":
            tool_func = getattr(tools, "fetch_cn_hk_quote_metrics", None)
        elif source == "search":
            tool_func = getattr(tools, "search", None)

        if tool_func:
            return tool_func(ticker)
        return None

    async def _first_summary(self, data: Any) -> str:
        deterministic = self._deterministic_summary(data)
        analysis = await self._llm_analyze(
            deterministic,
            role="资深A股量化交易分析师",
            focus="解读当前价格与日内变动，结合换手率和板块联动判断短线风险偏好。",
        )
        return analysis if analysis else deterministic

    def _deterministic_summary(self, data: Any) -> str:
        """Build a human-readable price snapshot from raw data."""
        if isinstance(data, dict):
            ticker = data.get("ticker", "N/A")
            price = data.get("price", "N/A")
            currency = data.get("currency", "CNY")
            change_pct = data.get("change_percent") or data.get("change_pct")
            text = f"{ticker} 当前价格: {currency} {price}"
            if change_pct is not None:
                try:
                    pct = float(change_pct)
                    direction = "上涨" if pct >= 0 else "下跌"
                    text += f"，日内{direction} {pct:+.2f}%"
                except (TypeError, ValueError):
                    pass
            # Add turnover info if available
            turnover = data.get("turnover_rate")
            if turnover is not None:
                text += f"，换手率 {turnover}%"
            return text + "。"
        elif isinstance(data, str) and data:
            return data
        return str(data)

    def _format_output(self, summary: str, raw_data: Any) -> AgentOutput:
        if isinstance(raw_data, dict):
            price = raw_data.get("price", "N/A")
            currency = raw_data.get("currency", "CNY")
            ticker = raw_data.get("ticker", "UNKNOWN")
            source = raw_data.get("source", "rqdatac")
            as_of = raw_data.get("as_of", datetime.now().isoformat())
            fallback_used = raw_data.get("fallback_used", False)
            change = raw_data.get("change")
            change_percent = raw_data.get("change_percent")
            if change_percent is None:
                change_percent = raw_data.get("change_pct")
            if change_percent is not None:
                try:
                    change_percent = float(change_percent)
                except Exception:
                    change_percent = None
            summary_text = f"{ticker} 当前价格: {currency} {price}。"
            if change_percent is not None:
                direction = "上涨" if change_percent >= 0 else "下跌"
                summary_text += f" 日内变动 {change_percent:+.2f}%（{direction}）。"
            evidence_text = str(raw_data)
            if isinstance(summary, str) and len(summary) > 150:
                summary_text = summary
        elif isinstance(raw_data, str) and raw_data:
            summary_text = raw_data
            source = "rqdatac"
            as_of = datetime.now().isoformat()
            fallback_used = False
            evidence_text = raw_data
        else:
            summary_text = summary or "价格数据获取失败"
            source = "unknown"
            as_of = datetime.now().isoformat()
            fallback_used = True
            evidence_text = str(raw_data) if raw_data else "暂无数据"

        evidence = [
            EvidenceItem(
                text=evidence_text,
                source=source,
                timestamp=as_of,
            )
        ]
        data_sources = [source]

        fallback_reason = None
        if fallback_used:
            if isinstance(raw_data, dict):
                fallback_reason = str(raw_data.get("fallback_detail") or raw_data.get("error") or "primary_source_unavailable")
            else:
                fallback_reason = "no_structured_data"

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary_text,
            evidence=evidence,
            confidence=1.0 if not fallback_used else 0.5,
            data_sources=data_sources,
            as_of=as_of,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            retryable=True,
        )
