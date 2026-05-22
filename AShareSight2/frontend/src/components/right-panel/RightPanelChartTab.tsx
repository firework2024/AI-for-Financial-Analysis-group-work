import { useState } from 'react';
import { Maximize2, TrendingUp, X } from 'lucide-react';
import { StockChart } from '../StockChart';
import { Dialog } from '../ui/Dialog';

export function RightPanelChartTab() {
  const [chartHeight, setChartHeight] = useState(250);
  const [isChartMaximized, setIsChartMaximized] = useState(false);

  return (
    <>
      <div className="flex-1 overflow-hidden p-3 flex flex-col">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold text-ash-text-secondary">Market Chart</span>
          <button
            type="button"
            onClick={() => setIsChartMaximized(true)}
            className="p-1 hover:bg-ash-hover rounded text-ash-muted hover:text-ash-primary transition-colors"
            title="Maximize"
          >
            <Maximize2 size={12} />
          </button>
        </div>
        <div className="flex-1 relative min-h-0">
          <div style={{ height: chartHeight }} className="w-full bg-ash-bg-secondary/50 rounded-lg overflow-hidden">
            <StockChart />
          </div>
          <div
            className="absolute bottom-0 left-0 right-0 h-3 cursor-ns-resize bg-gradient-to-t from-ash-border/30 to-transparent flex items-center justify-center"
            onMouseDown={(event) => {
              const startY = event.clientY;
              const startHeight = chartHeight;
              const onMouseMove = (moveEvent: MouseEvent) => {
                const diff = moveEvent.clientY - startY;
                setChartHeight(Math.max(150, Math.min(500, startHeight + diff)));
              };
              const onMouseUp = () => {
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
              };
              document.addEventListener('mousemove', onMouseMove);
              document.addEventListener('mouseup', onMouseUp);
            }}
          >
            <div className="w-8 h-1 bg-ash-border rounded-full" />
          </div>
        </div>
      </div>

      <Dialog
        open={isChartMaximized}
        onClose={() => setIsChartMaximized(false)}
        labelledBy="right-panel-chart-title"
        overlayClassName="p-6"
        panelClassName="bg-ash-panel border border-ash-border rounded-xl w-full max-w-5xl h-[80vh] flex flex-col shadow-2xl"
      >
        <div className="flex items-center justify-between p-4 border-b border-ash-border/50">
          <div className="flex items-center gap-2">
            <TrendingUp className="text-ash-primary" size={20} />
            <h2 id="right-panel-chart-title" className="font-bold text-lg text-ash-text">
              Market Chart (Full View)
            </h2>
          </div>
          <button
            type="button"
            onClick={() => setIsChartMaximized(false)}
            className="p-2 hover:bg-ash-hover rounded-full text-ash-muted hover:text-ash-text transition-colors"
            aria-label="Close full chart"
          >
            <X size={20} />
          </button>
        </div>
        <div className="flex-1 p-4 overflow-hidden bg-ash-bg-secondary/30">
          <StockChart />
        </div>
      </Dialog>
    </>
  );
}
