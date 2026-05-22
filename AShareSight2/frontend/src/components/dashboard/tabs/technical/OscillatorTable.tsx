/**
 * OscillatorTable - Oscillator indicators table.
 *
 * Rows: RSI / StochK / StochD / MACD / ADX / CCI / Williams%R
 * Columns: Value + Signal
 */
import type { TechnicalData } from '../../../../types/dashboard';

// --- Props ---

interface OscillatorTableProps {
  technicals?: TechnicalData | null;
}

// --- Types ---

type OscSignal = 'buy' | 'sell' | 'neutral';

interface OscRow {
  label: string;
  value: number | null | undefined;
  signal: OscSignal;
}

// --- Helpers ---

const fmtVal = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '--';
  return v.toFixed(2);
};

const SIGNAL_DISPLAY: Record<OscSignal, { label: string; className: string }> = {
  buy: { label: '买入', className: 'text-ash-success' },
  sell: { label: '卖出', className: 'text-ash-danger' },
  neutral: { label: '中性', className: 'text-ash-warning' },
};

function buildRows(technicals: TechnicalData | null | undefined): OscRow[] {
  if (!technicals) return [];

  const rows: OscRow[] = [];

  // RSI
  const rsi = technicals.rsi;
  rows.push({
    label: 'RSI (14)',
    value: rsi,
    signal: rsi == null ? 'neutral' : rsi < 30 ? 'buy' : rsi > 70 ? 'sell' : 'neutral',
  });

  // Stochastic K
  const stochK = technicals.stoch_k;
  rows.push({
    label: 'Stoch %K',
    value: stochK,
    signal: stochK == null ? 'neutral' : stochK < 20 ? 'buy' : stochK > 80 ? 'sell' : 'neutral',
  });

  // Stochastic D
  const stochD = technicals.stoch_d;
  rows.push({
    label: 'Stoch %D',
    value: stochD,
    signal: stochD == null ? 'neutral' : stochD < 20 ? 'buy' : stochD > 80 ? 'sell' : 'neutral',
  });

  // MACD
  const macdHist = technicals.macd_hist;
  rows.push({
    label: 'MACD',
    value: technicals.macd,
    signal: macdHist == null ? 'neutral' : macdHist > 0 ? 'buy' : macdHist < 0 ? 'sell' : 'neutral',
  });

  // ADX
  const adx = technicals.adx;
  rows.push({
    label: 'ADX (14)',
    value: adx,
    signal: adx == null ? 'neutral' : adx > 25 ? 'buy' : 'neutral',
  });

  // CCI
  const cci = technicals.cci;
  rows.push({
    label: 'CCI (20)',
    value: cci,
    signal: cci == null ? 'neutral' : cci < -100 ? 'buy' : cci > 100 ? 'sell' : 'neutral',
  });

  // Williams %R
  const wr = technicals.williams_r;
  rows.push({
    label: 'Williams %R',
    value: wr,
    signal: wr == null ? 'neutral' : wr < -80 ? 'buy' : wr > -20 ? 'sell' : 'neutral',
  });

  return rows;
}

// --- Component ---

export function OscillatorTable({ technicals }: OscillatorTableProps) {
  const rows = buildRows(technicals);

  if (rows.length === 0) {
    return (
      <div className="p-4 bg-ash-card rounded-xl border border-ash-border">
        <div className="text-xs font-medium text-ash-muted mb-3">震荡指标</div>
        <div className="text-sm text-ash-muted">--</div>
      </div>
    );
  }

  return (
    <div className="p-4 bg-ash-card rounded-xl border border-ash-border">
      <div className="text-xs font-medium text-ash-muted mb-3">震荡指标</div>

      <table className="w-full text-2xs">
        <thead>
          <tr className="border-b border-ash-border">
            <th className="text-left py-2 text-ash-muted font-medium">指标</th>
            <th className="text-right py-2 text-ash-muted font-medium">数值</th>
            <th className="text-right py-2 text-ash-muted font-medium">信号</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const display = SIGNAL_DISPLAY[row.signal];
            return (
              <tr key={row.label} className="border-b border-ash-border/50 last:border-b-0">
                <td className="py-2 text-ash-text font-medium">{row.label}</td>
                <td className="text-right py-2 tabular-nums text-ash-text">{fmtVal(row.value)}</td>
                <td className={`text-right py-2 font-medium ${display.className}`}>
                  {display.label}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default OscillatorTable;
