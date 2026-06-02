'use client';

import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Download, TrendingDown, Plane, CreditCard } from 'lucide-react';

interface HotelRec {
  category: string;
  item_title: string;
  item_price: number;
  currency: string;
  card: { name: string; bank: string; network: string };
  savings: number;
  effective_price: number;
  benefit: { reward_pct: number; cashback_pct: number; discount_pct: number; forex_pct: number; effective_pct: number };
}

type Rec = HotelRec;

interface Props {
  result: {
    report: string;
    recommendations: unknown[];
    flights: unknown[];
    hotels: unknown[];
  };
  onReset: () => void;
}

type Tab = 'report' | 'cards' | 'flights';

export default function ReportViewer({ result, onReset }: Props) {
  const [tab, setTab] = useState<Tab>('report');
  const recs          = result.recommendations as Rec[];
  const totalSavings  = recs.reduce((s, r) => s + (r.savings ?? 0), 0);
  const topCurrency   = recs[0]?.currency ?? 'USD';

  function downloadReport() {
    const blob = new Blob([result.report], { type: 'text/markdown' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'trip_report.md';
    a.click();
  }

  const tabs: { id: Tab; icon: React.ReactNode; label: string; count?: number }[] = [
    { id: 'report',  icon: <TrendingDown size={13} />, label: 'Report' },
    { id: 'cards',   icon: <CreditCard size={13} />,   label: 'Cards',   count: recs.length },
    { id: 'flights', icon: <Plane size={13} />,        label: 'Flights', count: result.flights.length },
  ];

  return (
    <div className="max-w-5xl mx-auto space-y-4 animate-fade-in">
      {/* Savings hero */}
      {totalSavings > 0 && (
        <div className="bg-gradient-to-r from-green-500 via-emerald-600 to-brand rounded-[2rem] p-6 flex items-center justify-between shadow-xl shadow-emerald-900/15">
          <div>
            <p className="text-green-100 text-xs font-bold uppercase tracking-widest mb-1">Potential Savings Found</p>
            <p className="text-4xl font-extrabold text-white">{topCurrency} {totalSavings.toFixed(0)}</p>
            <p className="text-green-100 text-sm mt-1">across {recs.length} card recommendation{recs.length !== 1 ? 's' : ''}</p>
          </div>
          <div className="w-16 h-16 bg-white/20 rounded-2xl flex items-center justify-center">
            <TrendingDown size={32} className="text-white" />
          </div>
        </div>
      )}

      {/* Tab bar */}
      <div className="card-white p-1.5 flex gap-1">
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`flex-1 flex items-center justify-center gap-1.5 text-xs font-semibold py-3 rounded-2xl transition-all ${
              tab === t.id ? 'bg-gradient-to-r from-brand to-emerald-600 text-white shadow-sm' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
            }`}>
            {t.icon} {t.label}
            {t.count !== undefined && t.count > 0 && (
              <span className={`text-xs px-1.5 py-0.5 rounded-full ${tab === t.id ? 'bg-white/20 text-white' : 'bg-gray-100 text-gray-500'}`}>
                {t.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── Report ── */}
      {tab === 'report' && (
        <div className="card-white overflow-hidden">
          <div className="flex items-center justify-between gap-3 px-5 py-3.5 border-b border-gray-100 bg-white/70">
            <p className="text-sm font-bold text-gray-700">Full Trip Report</p>
            <button onClick={downloadReport}
              className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-brand border border-gray-200 hover:border-brand rounded-lg px-3 py-1.5 transition-all">
              <Download size={12} /> Download .md
            </button>
          </div>
          <div className="p-6 report-body max-h-[70vh] overflow-y-auto">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.report}</ReactMarkdown>
          </div>
        </div>
      )}

      {/* ── Cards ── */}
      {tab === 'cards' && (
        <div className="space-y-3">
          {recs.length === 0 ? (
            <div className="card-white p-10 text-center">
              <p className="text-sm text-gray-400">No card recommendations generated.</p>
            </div>
          ) : recs.map((rec, i) => (
            <div key={i} className="card-white workflow-card p-5 hover:shadow-card-hover transition-shadow">
              <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-4">
                <div>
                  <span className="badge-brand mb-2 inline-block">{rec.category}</span>
                  <p className="text-base font-bold text-gray-800">{rec.card.name}</p>
                  <p className="text-xs text-gray-400 mt-0.5">{rec.card.bank} · {rec.card.network.toUpperCase()}</p>
                </div>
                <div className="text-right">
                  <p className="text-2xl font-extrabold text-green-600">Save {rec.currency} {rec.savings.toFixed(0)}</p>
                  <p className="text-xs text-gray-400 mt-0.5">Effective: {rec.currency} {rec.effective_price.toFixed(0)}</p>
                </div>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
                <BenefitPill label="Reward"   value={`${rec.benefit.reward_pct}%`}   positive />
                <BenefitPill label="Cashback" value={`${rec.benefit.cashback_pct}%`} positive />
                <BenefitPill label="Discount" value={`${rec.benefit.discount_pct}%`} positive />
                <BenefitPill label="Forex"    value={`-${rec.benefit.forex_pct}%`}   positive={false} />
              </div>
              <div className="flex items-center justify-between">
                <p className="text-xs font-bold text-brand">
                  Net: {rec.benefit.effective_pct > 0 ? '+' : ''}{rec.benefit.effective_pct.toFixed(1)}% effective savings
                </p>
                <div className="flex items-center gap-2">
                  <div className="h-1.5 w-28 bg-gray-100 rounded-full overflow-hidden">
                    <div className="h-full rounded-full"
                      style={{ width: `${Math.min(Math.abs(rec.benefit.effective_pct) * 6, 100)}%`, background: 'linear-gradient(to right, #003580, #16a34a)' }} />
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Flights ── */}
      {tab === 'flights' && (
        <div className="space-y-2">
          {result.flights.length === 0 ? (
            <div className="card-white p-10 text-center">
              <p className="text-sm text-gray-400">No flight data available.</p>
            </div>
          ) : (result.flights as Array<Record<string, string | number>>).slice(0, 15).map((f, i) => (
            <div key={i} className="card-white px-5 py-4 flex flex-col sm:flex-row sm:items-center gap-4 hover:shadow-card-hover transition-shadow">
              <div className="w-10 h-10 bg-gray-50 border border-gray-100 rounded-xl flex items-center justify-center flex-shrink-0 overflow-hidden">
                <Plane size={18} className="text-brand" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <p className="text-sm font-bold text-gray-800 truncate">
                    {String(f.provider || '').replace(/^Duffel \(/, '').replace(/\)$/, '')}
                  </p>
                  {f.source === 'duffel' && <span className="badge-brand flex-shrink-0">live</span>}
                </div>
                <p className="text-xs text-gray-400">
                  {String(f.departure || '-').slice(0, 16)} · {f.duration || '-'} · {f.stops ?? '0'} stop{f.stops !== 1 ? 's' : ''}
                </p>
              </div>
              <div className="text-left sm:text-right flex-shrink-0 w-full sm:w-auto">
                <p className="text-xl font-extrabold text-green-600">{f.currency} {Number(f.price).toFixed(0)}</p>
                {f.url ? (
                  <a href={String(f.url)} target="_blank" rel="noopener noreferrer"
                    className="text-xs text-brand hover:underline font-semibold">Book ↗</a>
                ) : <p className="text-xs text-gray-300">-</p>}
              </div>
            </div>
          ))}
        </div>
      )}

      <button onClick={onReset}
        className="w-full border-2 border-gray-200 hover:border-brand text-gray-400 hover:text-brand text-sm font-semibold py-3 rounded-xl transition-all">
        ← New Search
      </button>
    </div>
  );
}

function BenefitPill({ label, value, positive }: { label: string; value: string; positive: boolean }) {
  return (
    <div className={`rounded-xl px-2 py-2 text-center border ${positive ? 'bg-green-50 border-green-100' : 'bg-red-50 border-red-100'}`}>
      <p className="text-gray-400 text-xs leading-none mb-1">{label}</p>
      <p className={`font-bold text-sm ${positive ? 'text-green-600' : 'text-red-500'}`}>{value}</p>
    </div>
  );
}
