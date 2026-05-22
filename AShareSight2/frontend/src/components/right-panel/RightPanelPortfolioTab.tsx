import type { Dispatch, SetStateAction } from 'react';
import type { PortfolioRow, PortfolioSummary } from './types';
import { formatPct } from './utils';

type RightPanelPortfolioTabProps = {
  positionRows: PortfolioRow[];
  portfolioSummary: PortfolioSummary | null;
  isPortfolioEditing: boolean;
  positionDrafts: Record<string, string>;
  setPositionDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  onStartPortfolioEdit: () => void;
  onCancelPortfolioEdit: () => void;
  onSavePortfolioEdit: () => void;
};

export function RightPanelPortfolioTab({
  positionRows,
  portfolioSummary,
  isPortfolioEditing,
  positionDrafts,
  setPositionDrafts,
  onStartPortfolioEdit,
  onCancelPortfolioEdit,
  onSavePortfolioEdit,
}: RightPanelPortfolioTabProps) {
  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-ash-text-secondary">Portfolio</span>
        <button
          type="button"
          onClick={() => (isPortfolioEditing ? onSavePortfolioEdit() : onStartPortfolioEdit())}
          className="text-2xs px-2 py-0.5 rounded-full border border-ash-border text-ash-muted hover:text-ash-primary hover:border-ash-primary transition-colors"
        >
          {isPortfolioEditing ? 'Save' : 'Edit'}
        </button>
      </div>

      {isPortfolioEditing ? (
        <div className="space-y-3">
          {positionRows.length > 0 ? (
            <div className="space-y-2">
              {positionRows.map((item) => (
                <div key={item.ticker} className="flex items-center justify-between gap-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-ash-text">{item.ticker}</span>
                    <span className="text-2xs text-ash-muted">
                      {typeof item.price === 'number' ? `$${item.price.toFixed(2)}` : '--'}
                    </span>
                  </div>
                  <input
                    type="number"
                    inputMode="decimal"
                    min="0"
                    step="0.01"
                    value={positionDrafts[item.ticker] ?? ''}
                    onChange={(event) =>
                      setPositionDrafts((prev) => ({ ...prev, [item.ticker]: event.target.value }))
                    }
                    className="w-20 px-2 py-1 rounded border border-ash-border bg-ash-bg text-ash-text text-right text-xs focus:outline-none focus:border-ash-primary"
                    placeholder="0"
                  />
                </div>
              ))}
            </div>
          ) : (
            <div className="text-xs text-ash-muted">Add watchlist tickers to set holdings.</div>
          )}
          <div className="flex items-center justify-between text-2xs text-ash-muted">
            <span>Blank or 0 removes a position.</span>
            <button type="button" onClick={onCancelPortfolioEdit} className="hover:text-ash-text">
              Cancel
            </button>
          </div>
        </div>
      ) : portfolioSummary ? (
        <div className="space-y-3">
          <div className="space-y-1">
            <div className="text-xl font-bold text-ash-text">${portfolioSummary.totalValue.toLocaleString()}</div>
            <div className={`text-sm font-medium ${portfolioSummary.dayChange >= 0 ? 'text-ash-success' : 'text-ash-danger'}`}>
              {portfolioSummary.dayChange >= 0 ? '+' : ''}
              {portfolioSummary.dayChange.toFixed(2)} ({formatPct(portfolioSummary.avgChange)})
            </div>
            <div className="text-2xs text-ash-muted">Holdings {portfolioSummary.holdingsCount}</div>
          </div>
          <div className="space-y-2">
            {portfolioSummary.holdings.map((item) => (
              <div key={item.ticker} className="flex items-center justify-between text-xs">
                <div className="flex flex-col">
                  <span className="font-semibold text-ash-text">{item.ticker}</span>
                  <span className="text-2xs text-ash-muted">
                    {item.shares} shares{typeof item.price === 'number' ? ` @ $${item.price.toFixed(2)}` : ''}
                  </span>
                </div>
                <div className="text-right">
                  <div className="text-ash-text">${item.value.toLocaleString()}</div>
                  <div className={`text-2xs ${item.dayChange >= 0 ? 'text-ash-success' : 'text-ash-danger'}`}>
                    {item.dayChange >= 0 ? '+' : ''}
                    {item.dayChange.toFixed(2)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="text-xs text-ash-muted py-4 text-center">Set holdings to generate portfolio summary.</div>
      )}
    </div>
  );
}

