/**
 * MetricsBar - Horizontal key-indicator strip for the v2 dashboard.
 *
 * Shows 7 valuation metrics in a compact row:
 * Market Cap / PE / PB / EPS / Dividend Yield / 52-Week Range / Beta
 *
 * Gracefully degrades to "--" when data is null or missing.
 */
import type { ValuationData, SnapshotData } from '../../types/dashboard';

// --- Props ---

interface MetricsBarProps {
  valuation?: ValuationData | null;
  snapshot?: SnapshotData | null;
  loading?: boolean;
}

// --- Helpers ---

/** Format large numbers into compact currency (CNY) */
const fmtCap = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '--';
  if (v >= 1e12) return `¥${(v / 1e12).toFixed(2)}万亿`;
  if (v >= 1e8) return `¥${(v / 1e8).toFixed(1)}亿`;
  if (v >= 1e4) return `¥${(v / 1e4).toFixed(1)}万`;
  return `¥${v.toLocaleString()}`;
};

/** Format a ratio (PE, PB, etc.) to 1 decimal */
const fmtRatio = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '--';
  return v.toFixed(1);
};

/** Format a percentage (dividend yield) */
const fmtPct = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '--';
  return `${(v * 100).toFixed(2)}%`;
};

/** Format a price (52-week range) */
const fmtPrice = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '--';
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
};

// --- Metric Definition ---

interface MetricDef {
  label: string;
  value: string;
}

function buildMetrics(
  valuation: ValuationData | null | undefined,
  snapshot: SnapshotData | null | undefined,
): MetricDef[] {
  const v = valuation ?? {};
  const s = snapshot ?? {};

  const w52Low = fmtPrice(v.week52_low);
  const w52High = fmtPrice(v.week52_high);
  const rangeStr = w52Low === '--' && w52High === '--' ? '--' : `${w52Low} - ${w52High}`;

  return [
    { label: '总市值', value: fmtCap(v.market_cap) },
    { label: 'P/E', value: fmtRatio(v.trailing_pe) },
    { label: 'P/B', value: fmtRatio(v.price_to_book) },
    { label: 'EPS', value: s.eps !== null && s.eps !== undefined ? `¥${s.eps.toFixed(2)}` : '--' },
    { label: '股息率', value: fmtPct(v.dividend_yield) },
    { label: '52周范围', value: rangeStr },
    { label: 'Beta', value: fmtRatio(v.beta) },
  ];
}

// --- Component ---

export function MetricsBar({ valuation, snapshot, loading }: MetricsBarProps) {
  if (loading) {
    return (
      <div className="flex items-stretch gap-0 border-b border-ash-border bg-ash-card overflow-x-auto scrollbar-hide">
        {Array.from({ length: 7 }).map((_, i) => (
          <div
            key={i}
            className="flex-none px-4 py-2.5 border-r border-ash-border last:border-r-0"
          >
            <div className="h-3 w-12 bg-ash-border rounded animate-pulse mb-1.5" />
            <div className="h-5 w-16 bg-ash-border rounded animate-pulse" />
          </div>
        ))}
      </div>
    );
  }

  const metrics = buildMetrics(valuation, snapshot);

  return (
    <div className="flex items-stretch gap-0 border-b border-ash-border bg-ash-card overflow-x-auto scrollbar-hide">
      {metrics.map((m) => (
        <div
          key={m.label}
          className="flex-none px-4 py-2.5 border-r border-ash-border last:border-r-0"
        >
          <div className="text-2xs text-ash-muted whitespace-nowrap">{m.label}</div>
          <div className="text-sm font-semibold text-ash-text tabular-nums whitespace-nowrap mt-0.5">
            {m.value}
          </div>
        </div>
      ))}
    </div>
  );
}

export default MetricsBar;
