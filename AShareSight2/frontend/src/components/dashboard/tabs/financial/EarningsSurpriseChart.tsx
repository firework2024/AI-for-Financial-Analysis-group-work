/**
 * EarningsSurpriseChart — quarterly EPS bar chart.
 *
 * When consensus forecast data is available, shows estimate vs actual
 * grouped bars with a surprise percentage line overlay.
 * When only actual EPS is available, shows a single-bar chart.
 */
import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';

import { useChartTheme } from '../../../../hooks/useChartTheme';
import type { EarningsHistoryEntry } from '../../../../types/dashboard';

// --- Props ---

interface EarningsSurpriseChartProps {
  data?: EarningsHistoryEntry[] | null;
}

// --- Component ---

export function EarningsSurpriseChart({ data }: EarningsSurpriseChartProps) {
  const theme = useChartTheme();

  const option = useMemo(() => {
    if (!data || data.length === 0) return null;

    const sorted = [...data].slice(-8);
    const quarters = sorted.map((e) => e.quarter);
    const actuals = sorted.map((e) => e.eps_actual ?? null);
    const estimates = sorted.map((e) => e.eps_estimate ?? null);
    const hasEstimates = estimates.some((v) => v != null);
    const surprises = sorted.map((e) =>
      e.surprise_pct != null ? Math.round(e.surprise_pct * 100) / 100 : null,
    );
    const hasSurprises = surprises.some((v) => v != null);

    const legendData = hasEstimates
      ? ['预期 EPS', '实际 EPS', '惊喜率']
      : ['季度 EPS'];

    const series: any[] = hasEstimates
      ? [
          {
            name: '预期 EPS',
            type: 'bar',
            data: estimates,
            barMaxWidth: 20,
            itemStyle: { color: theme.primarySoft, borderRadius: [2, 2, 0, 0] },
          },
          {
            name: '实际 EPS',
            type: 'bar',
            data: actuals.map((v, i) => ({
              value: v,
              itemStyle: {
                color:
                  v != null && estimates[i] != null && v >= (estimates[i] ?? 0)
                    ? theme.success
                    : theme.danger,
                borderRadius: [2, 2, 0, 0],
              },
            })),
            barMaxWidth: 20,
          },
          ...(hasSurprises
            ? [
                {
                  name: '惊喜率',
                  type: 'line' as const,
                  yAxisIndex: 1,
                  data: surprises,
                  smooth: true,
                  showSymbol: true,
                  symbolSize: 5,
                  lineStyle: { color: theme.warning, width: 2 },
                  itemStyle: { color: theme.warning },
                },
              ]
            : []),
        ]
      : [
          {
            name: '季度 EPS',
            type: 'bar',
            data: actuals.map((v) => ({
              value: v,
              itemStyle: {
                color: theme.primary,
                borderRadius: [2, 2, 0, 0],
              },
            })),
            barMaxWidth: 28,
          },
        ];

    const title = hasEstimates ? '季度 EPS 预期 vs 实际' : '季度 EPS';

    return {
      tooltip: {
        trigger: 'axis' as const,
        axisPointer: { type: 'shadow' },
        backgroundColor: theme.tooltipBackground,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
      },
      legend: {
        data: legendData,
        textStyle: { color: theme.muted, fontSize: 10 },
        top: 0,
        itemWidth: 12,
        itemHeight: 8,
      },
      grid: { left: 48, right: hasSurprises ? 48 : 20, top: 32, bottom: 8, containLabel: false },
      xAxis: {
        type: 'category' as const,
        data: quarters,
        axisLine: { lineStyle: { color: theme.border } },
        axisLabel: { color: theme.muted, fontSize: 9, rotate: 30 },
      },
      yAxis: [
        {
          type: 'value' as const,
          axisLabel: { color: theme.muted, fontSize: 9, formatter: '{value}' },
          splitLine: { lineStyle: { color: theme.grid, type: 'dashed' } },
        },
        ...(hasSurprises
          ? [
              {
                type: 'value' as const,
                axisLabel: { color: theme.muted, fontSize: 9, formatter: '{value}%' },
                splitLine: { show: false },
              },
            ]
          : []),
      ],
      series,
    };
  }, [data, theme]);

  if (!option) {
    return (
      <div className="p-4 bg-ash-card rounded-xl border border-ash-border">
        <div className="text-xs font-medium text-ash-muted mb-3">季度 EPS</div>
        <div className="text-sm text-ash-muted">暂无盈利数据</div>
      </div>
    );
  }

  return (
    <div className="p-4 bg-ash-card rounded-xl border border-ash-border">
      <div className="text-xs font-medium text-ash-muted mb-2">季度 EPS</div>
      <ReactECharts
        option={option}
        style={{ width: '100%', height: 240 }}
        opts={{ renderer: 'svg' }}
        notMerge
        lazyUpdate
      />
    </div>
  );
}

export default EarningsSurpriseChart;
