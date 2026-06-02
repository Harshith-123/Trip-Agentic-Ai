'use client';

import { useState } from 'react';
import { Plane, Hotel, TrendingDown, ExternalLink } from 'lucide-react';

interface Flight {
  provider: string; airline: string; price: number; currency: string;
  departure: string; arrival: string; duration: string; stops: string; url: string; source?: string;
}
interface Hotel {
  title: string; provider: string; chain: string | null;
  price: number; currency: string; per_night: boolean; url: string;
}
interface Props { flights: Flight[]; hotels: Hotel[]; onReset: () => void; }

type Tab = 'flights' | 'hotels';

export default function ScraperResults({ flights, hotels, onReset }: Readonly<Props>) {
  const [tab, setTab] = useState<Tab>('flights');

  const cheapestFlight = flights[0] ?? null;
  const cheapestHotel  = hotels[0]  ?? null;
  const avgFlight = flights.length > 1
    ? flights.slice(0, 5).reduce((s, f) => s + f.price, 0) / Math.min(flights.length, 5)
    : null;

  return (
    <div className="max-w-5xl mx-auto space-y-4 animate-fade-in">
      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard icon={<Plane size={16} />} label="Cheapest Flight"
          value={cheapestFlight ? `${cheapestFlight.currency} ${cheapestFlight.price.toFixed(0)}` : '-'}
          sub={cheapestFlight?.provider.split('(')[0].trim()} color="text-brand" bg="bg-blue-50" />
        <StatCard icon={<TrendingDown size={16} />} label="Avg Top-5"
          value={avgFlight ? `${cheapestFlight?.currency} ${avgFlight.toFixed(0)}` : '-'}
          sub="across platforms" color="text-purple-600" bg="bg-purple-50" />
        <StatCard icon={<Hotel size={16} />} label="Cheapest Hotel"
          value={cheapestHotel ? `${cheapestHotel.currency} ${cheapestHotel.price.toFixed(0)}` : '-'}
          sub={cheapestHotel ? `${cheapestHotel.provider} / night` : undefined} color="text-orange-600" bg="bg-orange-50" />
        <StatCard icon={<span className="text-sm">📊</span>} label="Total Results"
          value={`${flights.length + hotels.length}`}
          sub={`${flights.length} flights · ${hotels.length} hotels`} color="text-green-600" bg="bg-green-50" />
      </div>

      {/* Tabs */}
      <div className="card-white p-1.5 flex gap-1">
        {([
          { id: 'flights' as Tab, icon: <Plane size={13} />,  label: 'Flights', count: flights.length },
          { id: 'hotels'  as Tab, icon: <Hotel size={13} />,  label: 'Hotels',  count: hotels.length },
        ]).map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`flex-1 flex items-center justify-center gap-1.5 text-sm font-semibold py-3 rounded-2xl transition-all ${
              tab === t.id ? 'bg-gradient-to-r from-brand to-emerald-600 text-white shadow-sm' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
            }`}>
            {t.icon} {t.label}
            <span className={`text-xs px-1.5 py-0.5 rounded-full ${tab === t.id ? 'bg-white/20 text-white' : 'bg-gray-100 text-gray-500'}`}>
              {t.count}
            </span>
          </button>
        ))}
      </div>

      {/* Flights */}
      {tab === 'flights' && (
        <div className="space-y-2">
          {flights.length === 0 ? (
            <div className="card-white p-10 text-center"><p className="text-sm text-gray-400">No flights found.</p></div>
          ) : flights.slice(0, 30).map((f, i) => (
            <div key={i} className="card-white px-5 py-4 flex flex-col sm:flex-row sm:items-center gap-4 hover:shadow-card-hover transition-shadow">
              <div className="w-10 h-10 bg-blue-50 border border-blue-100 rounded-xl flex items-center justify-center flex-shrink-0">
                <Plane size={18} className="text-brand" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <p className="text-sm font-bold text-gray-800 truncate">
                    {f.airline || f.provider.split('(')[0].trim()}
                  </p>
                  {f.source === 'duffel' && <span className="badge-brand flex-shrink-0">live</span>}
                </div>
                <p className="text-xs text-gray-400">
                  {String(f.departure || '-').slice(0, 16)} · {f.duration || '-'} · {f.stops || '0'} stop{f.stops !== '1' ? 's' : ''}
                </p>
              </div>
              <div className="text-left sm:text-right flex-shrink-0 w-full sm:w-auto">
                <p className="text-xl font-extrabold text-green-600">{f.currency} {f.price.toFixed(0)}</p>
                {f.url ? (
                  <a href={f.url} target="_blank" rel="noopener noreferrer"
                    className="text-xs text-brand hover:underline font-semibold flex items-center gap-0.5 sm:justify-end">
                    Book <ExternalLink size={10} />
                  </a>
                ) : <p className="text-xs text-gray-300">-</p>}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Hotels */}
      {tab === 'hotels' && (
        <div className="space-y-2">
          {hotels.length === 0 ? (
            <div className="card-white p-10 text-center"><p className="text-sm text-gray-400">No hotels found.</p></div>
          ) : hotels.slice(0, 30).map((h, i) => (
            <div key={i} className="card-white px-5 py-4 flex flex-col sm:flex-row sm:items-center gap-4 hover:shadow-card-hover transition-shadow">
              <div className="w-10 h-10 bg-orange-50 border border-orange-100 rounded-xl flex items-center justify-center flex-shrink-0">
                <Hotel size={18} className="text-orange-500" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-bold text-gray-800 truncate mb-0.5">{h.title}</p>
                <p className="text-xs text-gray-400">{h.provider}{h.chain ? ` · ${h.chain}` : ''}</p>
              </div>
              <div className="text-left sm:text-right flex-shrink-0 w-full sm:w-auto">
                <p className="text-xl font-extrabold text-orange-600">{h.currency} {h.price.toFixed(0)}</p>
                <p className="text-xs text-gray-400">/ night</p>
                {h.url ? (
                  <a href={h.url} target="_blank" rel="noopener noreferrer"
                    className="text-xs text-brand hover:underline font-semibold flex items-center gap-0.5 sm:justify-end">
                    Book <ExternalLink size={10} />
                  </a>
                ) : null}
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

function StatCard({ icon, label, value, sub, color, bg }: { icon: React.ReactNode; label: string; value: string; sub?: string; color: string; bg: string }) {
  return (
      <div className="card-white workflow-card p-4">
      <div className={`w-8 h-8 ${bg} rounded-lg flex items-center justify-center mb-2 ${color}`}>{icon}</div>
      <p className="text-xs text-gray-400 mb-0.5">{label}</p>
      <p className={`text-lg font-extrabold ${color}`}>{value}</p>
      {sub && <p className="text-xs text-gray-400 truncate mt-0.5">{sub}</p>}
    </div>
  );
}
