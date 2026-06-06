'use client';

import { Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { Plane, Zap, ChevronRight } from 'lucide-react';
import TripForm from '@/components/TripForm';
import AgentProgress from '@/components/AgentProgress';
import ReportViewer from '@/components/ReportViewer';

type Step = 'form' | 'running' | 'done';

interface SessionResult {
  report: string;
  llm_insights: Record<string, unknown>;
  recommendations: unknown[];
  flights: unknown[];
  hotels: unknown[];
}

const STEPS: { id: Step; label: string }[] = [
  { id: 'form',    label: 'Trip Setup' },
  { id: 'running', label: 'AI Running' },
  { id: 'done',    label: 'Results' },
];

function AgentPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [step, setStep]           = useState<Step>('form');
  const [sessionId, setSessionId] = useState('');
  const [result, setResult]       = useState<SessionResult | null>(null);

  // If home page already started a session, go straight to running.
  // The WebSocket handles retries and errors; no pre-check needed.
  useEffect(() => {
    const sid = searchParams.get('session');
    if (!sid) return;
    setSessionId(sid);
    setStep('running');
  }, [searchParams]);

  function handleStart(sid: string)          { setSessionId(sid); setStep('running'); }
  function handleComplete(res: SessionResult) { setResult(res); setStep('done'); router.replace('/agent'); }
  function handleReset()                     { setStep('form'); setSessionId(''); setResult(null); }

  const stepIndex = STEPS.findIndex(s => s.id === step);

  return (
    <div className="app-background">
      {/* Nav */}
      <nav className="top-nav">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 flex items-center justify-between h-14">
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center gap-2 group">
              <div className="nav-brand-mark h-8 w-8 rounded-xl">
                <Plane size={15} />
              </div>
              <span className="text-white font-extrabold text-base">TravelSmart</span>
            </Link>
            <ChevronRight size={14} className="text-white/40" />
            <div className="flex items-center gap-1.5 text-white/90 text-sm font-semibold">
              <Zap size={14} className="text-yellow-300" /> AI Agent
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
          <div className="absolute -right-16 -top-16 h-40 w-40 rounded-full bg-brand/10 blur-2xl" />
          <div className="absolute -bottom-20 left-1/3 h-44 w-44 rounded-full bg-emerald-400/10 blur-2xl" />
          <div className="relative flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full bg-brand/10 px-3 py-1 text-xs font-bold uppercase tracking-widest text-brand mb-3">
                <Zap size={12} /> Guided AI workflow
              </div>
              <h1 className="text-3xl sm:text-4xl font-black tracking-tight text-slate-950">Build the best-value trip</h1>
              <p className="mt-2 max-w-2xl text-sm sm:text-base leading-relaxed text-slate-600">
                Add cards, set the route, watch each travel agent run, then review the final savings report in one place.
              </p>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center sm:w-72">
              {['Cards', 'Trip', 'Report'].map((item, i) => (
                <div key={item} className="rounded-2xl bg-white/75 p-3 shadow-sm shadow-slate-900/5 border border-white/80">
                  <p className="text-lg font-black text-brand">0{i + 1}</p>
                  <p className="text-[11px] font-bold uppercase tracking-widest text-slate-400">{item}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Step indicator */}
      <div className="max-w-5xl mx-auto px-4 pt-5">
        <div className="glass-panel p-3 flex items-center justify-center gap-0">
          {STEPS.map((s, i) => (
            <div key={s.id} className="flex items-center">
              <div className={`flex items-center gap-2 text-sm font-semibold px-1 ${
                step === s.id ? 'text-brand' : i < stepIndex ? 'text-green-600' : 'text-gray-400'
              }`}>
                <span className={`w-7 h-7 rounded-full border-2 flex items-center justify-center text-xs font-bold flex-shrink-0 ${
                  step === s.id   ? 'border-brand bg-brand text-white' :
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
        {step === 'form'    && <TripForm onStart={handleStart} />}
        {step === 'running' && <AgentProgress sessionId={sessionId} onComplete={handleComplete} />}
        {step === 'done' && result && <ReportViewer result={result} onReset={handleReset} />}
      </main>
    </div>
  );
}

export default function AgentPage() {
  return (
    <Suspense fallback={<div className="app-background" />}>
      <AgentPageContent />
    </Suspense>
  );
}
