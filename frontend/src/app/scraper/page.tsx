'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { Plane, Search, ChevronRight } from 'lucide-react';
import ScraperForm from '@/components/ScraperForm';
import ScraperResults from '@/components/ScraperResults';
import { wsUrl } from '@/lib/api';

type Step = 'form' | 'running' | 'done';
interface ScrapeResult { flights: unknown[]; hotels: unknown[]; }

const STEPS: { id: Step; label: string }[] = [
  { id: 'form',    label: 'Setup' },
  { id: 'running', label: 'Scraping' },
  { id: 'done',    label: 'Results' },
];

function lineColor(line: string): string {
  if (line.includes('✓') || line.includes('Done')) return 'text-green-600';
  if (line.includes('✗') || line.includes('ERROR')) return 'text-red-500';
  if (line.includes('[FLIGHTS]')) return 'text-brand';
  if (line.includes('[HOTELS]'))  return 'text-orange-500';
  return 'text-gray-500';
}

function ScraperProgress({ sessionId, onComplete }: Readonly<{ sessionId: string; onComplete: (r: ScrapeResult) => void }>) {
  const [lines,       setLines]       = useState<string[]>([]);
  const [wsStatus,    setWsStatus]    = useState<'connecting' | 'open' | 'closed'>('connecting');
  const [flightsDone, setFlightsDone] = useState(false);
  const [hotelsDone,  setHotelsDone]  = useState(false);
  const [fatalError,  setFatalError]  = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const wsRef     = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    if (wsRef.current) return;

    const ws = new WebSocket(wsUrl(`/ws/scrape/${sessionId}`));
    wsRef.current = ws;
    ws.onopen  = () => setWsStatus('open');
    ws.onclose = () => setWsStatus('closed');
    ws.onerror = () => {
      setLines(p => {
        if (p.length === 0) { setFatalError(true); return ['❌ Cannot connect to backend on port 8000']; }
        return p;
      });
      setWsStatus('closed');
    };
    ws.onmessage = (evt) => {
      const msg = JSON.parse(evt.data as string);
      if (msg.type === 'progress') {
        setLines(p => [...p, msg.data as string]);
        if ((msg.data as string).includes('[FLIGHTS]') && (msg.data as string).includes('Done')) setFlightsDone(true);
        if ((msg.data as string).includes('[HOTELS]')  && (msg.data as string).includes('Done')) setHotelsDone(true);
      }
      if (msg.type === 'complete') {
        setFlightsDone(true); setHotelsDone(true); setWsStatus('closed');
        onComplete({ flights: (msg.extras?.flights as unknown[]) ?? [], hotels: (msg.extras?.hotels as unknown[]) ?? [] });
      }
      if (msg.type === 'error') {
        setLines(p => [...p, `❌ ERROR: ${msg.data as string}`]);
        setFatalError(true);
        setWsStatus('closed');
      }
    };
    return () => { wsRef.current = null; ws.close(); };
  }, [sessionId, onComplete]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [lines]);

  const stages = [
    { key: 'flights', done: flightsDone, label: '✈️ Google Flights · Kayak · Skyscanner · MakeMyTrip' },
    { key: 'hotels',  done: hotelsDone,  label: '🏨 Booking.com · Expedia · Agoda · Airbnb · Chain sites' },
  ];
  const pct = Math.round((stages.filter(s => s.done).length / stages.length) * 100);

  return (
    <div className="max-w-5xl mx-auto space-y-4 animate-fade-in">
      <div className="card-white workflow-card p-5 sm:p-6">
        <div className="flex items-center justify-between mb-3">
          <div>
            <p className="text-sm font-bold text-gray-800">Scraper Progress</p>
            <p className="text-xs text-slate-500 mt-0.5">Flights and hotels run in parallel where available.</p>
          </div>
          <span className="text-xs text-gray-400 font-semibold">{pct}%</span>
        </div>
        <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden mb-5">
          <div className="h-full rounded-full transition-all duration-700" style={{ width: `${pct}%`, background: 'linear-gradient(to right, #003580, #16a34a)' }} />
        </div>
        <div className="space-y-2">
          {stages.map((s) => {
            const active = !s.done && wsStatus === 'open';
            return (
              <div key={s.key} className={`flex items-center gap-3 px-4 py-3 rounded-xl border transition-all ${
                s.done ? 'border-green-200 bg-green-50' : active ? 'border-blue-200 bg-blue-50' : 'border-gray-100 bg-gray-50'
              }`}>
                <div className={`w-6 h-6 rounded-full border-2 flex items-center justify-center text-xs flex-shrink-0 ${
                  s.done ? 'border-green-500 bg-green-500 text-white' : active ? 'border-[#003580] bg-blue-50 text-[#003580]' : 'border-gray-300 text-gray-400'
                }`}>
                  {s.done ? '✓' : active ? <span className="animate-pulse font-bold">·</span> : '…'}
                </div>
                <span className={`text-sm font-medium ${s.done ? 'text-green-700' : active ? 'text-brand' : 'text-gray-400'}`}>{s.label}</span>
                {active && <span className="text-xs text-brand animate-pulse ml-auto font-semibold">scraping…</span>}
              </div>
            );
          })}
        </div>
      </div>

      <div className="card-white overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 bg-white/70">
          <p className="text-sm font-semibold text-gray-600">Live Log</p>
          <div className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${wsStatus === 'open' ? 'bg-green-500 animate-pulse' : wsStatus === 'connecting' ? 'bg-yellow-500 animate-pulse' : 'bg-gray-300'}`} />
            <span className="text-xs text-gray-400 font-medium">{wsStatus === 'open' ? 'live' : wsStatus === 'connecting' ? 'connecting' : 'done'}</span>
          </div>
        </div>
        <div className="h-64 overflow-y-auto p-4 font-mono text-xs space-y-0.5 bg-slate-50/90">
          {lines.length === 0 && <p className="text-gray-400 animate-pulse py-2">Starting scrapers…</p>}
          {lines.map((line, i) => <div key={i} className={`leading-5 ${lineColor(line)}`}>{line}</div>)}
          <div ref={bottomRef} />
        </div>
      </div>
      {fatalError && wsStatus === 'closed' && (
        <div className="bg-red-50 border border-red-200 rounded-2xl p-5 text-center">
          <p className="text-sm font-bold text-red-600 mb-1">Cannot connect to backend</p>
          <p className="text-xs text-gray-500">
            Start the server:{' '}
            <code className="text-orange-600 bg-orange-50 px-1.5 py-0.5 rounded">uvicorn api.server:app --reload --port 8000</code>
          </p>
        </div>
      )}
    </div>
  );
}

export default function ScraperPage() {
  const [step,      setStep]      = useState<Step>('form');
  const [sessionId, setSessionId] = useState('');
  const [result,    setResult]    = useState<ScrapeResult>({ flights: [], hotels: [] });

  function handleStart(sid: string)        { setSessionId(sid); setStep('running'); }
  function handleComplete(r: ScrapeResult) { setResult(r); setStep('done'); }
  function handleReset()                   { setStep('form'); setSessionId(''); setResult({ flights: [], hotels: [] }); }

  const stepIndex = STEPS.findIndex(s => s.id === step);

  return (
    <div className="app-background">
      <nav className="top-nav">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 flex items-center justify-between h-14">
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center gap-2">
              <div className="nav-brand-mark h-8 w-8 rounded-xl">
                <Plane size={15} />
              </div>
              <span className="text-white font-extrabold text-base">TravelSmart</span>
            </Link>
            <ChevronRight size={14} className="text-white/40" />
            <div className="flex items-center gap-1.5 text-white/90 text-sm font-semibold">
              <Search size={14} className="text-green-300" /> Quick Scraper
            </div>
          </div>
          {step !== 'form' && (
            <button onClick={handleReset}
              className="text-white/70 hover:text-white hover:bg-white/10 text-xs font-medium px-3 py-1.5 rounded-lg transition-all">
              ← New Search
            </button>
          )}
        </div>
      </nav>

      <section className="max-w-5xl mx-auto px-4 pt-8 sm:pt-10">
        <div className="glass-panel workflow-card p-6 sm:p-8 overflow-hidden relative">
          <div className="absolute -right-16 -top-16 h-40 w-40 rounded-full bg-emerald-400/10 blur-2xl" />
          <div className="absolute -bottom-20 left-1/3 h-44 w-44 rounded-full bg-brand/10 blur-2xl" />
          <div className="relative flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full bg-emerald-500/10 px-3 py-1 text-xs font-bold uppercase tracking-widest text-emerald-700 mb-3">
                <Search size={12} /> Fast comparison mode
              </div>
              <h1 className="text-3xl sm:text-4xl font-black tracking-tight text-slate-950">Scrape travel platforms quickly</h1>
              <p className="mt-2 max-w-2xl text-sm sm:text-base leading-relaxed text-slate-600">
                Enter route and hotel details once, then compare flights and stays from multiple providers in a focused results view.
              </p>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center sm:w-72">
              {['Setup', 'Scrape', 'Compare'].map((item, i) => (
                <div key={item} className="rounded-2xl bg-white/75 p-3 shadow-sm shadow-slate-900/5 border border-white/80">
                  <p className="text-lg font-black text-emerald-700">0{i + 1}</p>
                  <p className="text-[11px] font-bold uppercase tracking-widest text-slate-400">{item}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <div className="max-w-5xl mx-auto px-4 pt-5">
        <div className="glass-panel p-3 flex items-center justify-center gap-0">
          {STEPS.map((s, i) => (
            <div key={s.id} className="flex items-center">
              <div className={`flex items-center gap-2 text-sm font-semibold px-1 ${
                step === s.id ? 'text-green-600' : i < stepIndex ? 'text-green-600' : 'text-gray-400'
              }`}>
                <span className={`w-7 h-7 rounded-full border-2 flex items-center justify-center text-xs font-bold flex-shrink-0 ${
                  step === s.id   ? 'border-green-500 bg-green-500 text-white' :
                  i < stepIndex   ? 'border-green-500 bg-green-500 text-white' :
                                    'border-gray-300 text-gray-400'
                }`}>
                  {i < stepIndex ? '✓' : i + 1}
                </span>
                <span className="hidden sm:inline">{s.label}</span>
              </div>
              {i < STEPS.length - 1 && (
                <div className={`w-10 sm:w-20 h-0.5 mx-2 rounded-full ${i < stepIndex ? 'bg-green-400' : 'bg-gray-200'}`} />
              )}
            </div>
          ))}
      </div>
      </div>

      <main className="max-w-5xl mx-auto px-4 py-8">
        {step === 'form'    && <ScraperForm onStart={handleStart} />}
        {step === 'running' && <ScraperProgress sessionId={sessionId} onComplete={handleComplete} />}
        {step === 'done'    && (
          <ScraperResults
            flights={result.flights as Parameters<typeof ScraperResults>[0]['flights']}
            hotels={result.hotels   as Parameters<typeof ScraperResults>[0]['hotels']}
            onReset={handleReset}
          />
        )}
      </main>
    </div>
  );
}
