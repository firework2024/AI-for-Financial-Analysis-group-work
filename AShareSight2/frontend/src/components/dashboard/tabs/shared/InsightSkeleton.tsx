/**
 * InsightSkeleton - Loading placeholder for AI insight cards.
 *
 * Displays animated pulse bars mimicking the AiInsightCard layout.
 */
export function InsightSkeleton() {
  return (
    <div className="bg-ash-card rounded-xl border border-ash-border p-4 animate-pulse">
      {/* Header row */}
      <div className="flex items-center gap-3 mb-3">
        <div className="w-10 h-10 rounded-full bg-ash-border" />
        <div className="flex-1">
          <div className="h-4 w-32 bg-ash-border rounded mb-1" />
          <div className="h-3 w-20 bg-ash-border rounded" />
        </div>
        <div className="w-12 h-6 bg-ash-border rounded" />
      </div>
      {/* Summary lines */}
      <div className="space-y-2 mb-3">
        <div className="h-3 w-full bg-ash-border rounded" />
        <div className="h-3 w-5/6 bg-ash-border rounded" />
        <div className="h-3 w-4/6 bg-ash-border rounded" />
      </div>
      {/* Key points */}
      <div className="space-y-1.5">
        <div className="h-3 w-3/4 bg-ash-border rounded" />
        <div className="h-3 w-2/3 bg-ash-border rounded" />
        <div className="h-3 w-1/2 bg-ash-border rounded" />
      </div>
    </div>
  );
}

export default InsightSkeleton;
