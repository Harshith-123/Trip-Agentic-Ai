'use client';

import { useEffect, useRef, useState } from 'react';
import { wsUrl } from '@/lib/api';

interface ProgressMsg {
  type: 'progress' | 'complete' | 'error';
  data: string;
  extras?: {
    llm_insights: Record<string, unknown>;
    recommendations: unknown[];
    flights: unknown[];
    hotels: unknown[];
  };
}

interface Props {
  sessionId: string;
  onComplete: (result: {
    report: string;
    llm_insights: Record<string, unknown>;
    recommendations: unknown[];
    flights: unknown[];
    hotels: unknown[];
  }) => void;
}

const STAGES = [
  { key: 'ORCHESTRATOR',      label: 'Planning',           icon: '🗺️',  bg: 'bg-blue-50',   text: 'text-blue-600',    border: 'border-blue-200' },
  { key: 'FLIGHT AGENT',      label: 'Fetching Flights',   icon: '✈️',  bg: 'bg-blue-50',   text: 'text-[#003580]',   border: 'border-blue-200' },
  { key: 'HOTEL AGENT',       label: 'Fetching Hotels',    icon: '🏨',  bg: 'bg-orange-50', text: 'text-orange-600',  border: 'border-orange-200' },
  { key: 'CONTEXT AGENT',     label: 'Destination Info',   icon: '🌍',  bg: 'bg-purple-50', text: 'text-purple-600',  border: 'border-purple-200' },
  { key: 'DATA MERGE',        label: 'Merging Data',       icon: '🔀',  bg: 'bg-cyan-50',   text: 'text-cyan-600',    border: 'border-cyan-200' },
  { key: 'CARD REWARDS',      label: 'Card Rewards',       icon: '💳',  bg: 'bg-green-50',  text: 'text-green-600',   border: 'border-green-200' },
  { key: 'VALIDATION',        label: 'Validating',         icon: '✅',  bg: 'bg-yellow-50', text: 'text-yellow-600',  border: 'border-yellow-200' },
  { key: 'LLM INSIGHTS',      label: 'AI Insights',        icon: '🤖',  bg: 'bg-pink-50',   text: 'text-pink-600',    border: 'border-pink-200' },
  { key: 'REPORT',            label: 'Generating Report',  icon: '📝',  bg: 'bg-indigo-50', text: 'text-indigo-600',  border: 'border-indigo-200' },
];

function detectStage(msg: string): string {
  for (const s of STAGES) { if (msg.includes(`[${s.key}]`)) return s.key; }
  return '';
}

function lineColor(line: string): string {
  if (line.includes('✓')) return 'text-green-600';
  if (line.includes('✗') || line.includes('ERROR')) return 'text-red-500';
  if (line.includes('⚠')) return 'text-orange-500';
  if (line.includes('[ORCHESTRATOR]'))  return 'text-blue-600';
  if (line.includes('[FLIGHT AGENT]'))  return 'text-brand';
  if (line.includes('[HOTEL AGENT]'))   return 'text-orange-500';
  if (line.includes('[CONTEXT AGENT]')) return 'text-purple-600';
  if (line.includes('[DATA MERGE]'))    return 'text-cyan-600';
  if (line.includes('[CARD REWARDS]'))  return 'text-green-600';
  if (line.includes('[VALIDATION]'))    return 'text-yellow-600';
  if (line.includes('[LLM INSIGHTS]'))  return 'text-pink-600';
  if (line.includes('[REPORT AGENT]'))  return 'text-indigo-600';
  return 'text-gray-500';
}

const STAGE_KEYS = STAGES.map(s => s.key);

export default function AgentProgress({ sessionId, onComplete }: Props) {
  const [lines, setLines]             = useState<string[]>([]);
  const [activeStage, setActiveStage] = useState<string>('ORCHESTRATOR');
  const [doneStages, setDoneStages]   = useState<Set<string>>(new Set());
  const [wsStatus, setWsStatus]       = useState<'connecting' | 'open' | 'closed'>('connecting');
  const [fatalError, setFatalError]   = useState(false);
  const bottomRef  = useRef<HTMLDivElement>(null);
  const wsRef      = useRef<WebSocket | null>(null);
  const stageKeys  = STAGE_KEYS;
  const pct = Math.round((doneStages.size / STAGES.length) * 100);

  useEffect(() => {
    if (!sessionId) return;

    let cancelled = false;
    let ws: WebSocket | null = null;

    // Small delay so Strict Mode's first-mount cleanup fires before we open the socket
    const timer = setTimeout(() => {
      if (cancelled) return;

      ws = new WebSocket(wsUrl(`/ws/${sessionId}`));
      wsRef.current = ws;

      ws.onopen = () => { if (!cancelled) setWsStatus('open'); };

      ws.onmessage = (evt) => {
        if (cancelled) return;
        const msg: ProgressMsg = JSON.parse(evt.data);
        if (msg.type === 'progress') {
          setLines(prev => [...prev, msg.data]);
          const stage = detectStage(msg.data);
          if (stage) {
            setActiveStage(stage);
            setDoneStages(prev => {
              const next = new Set(prev);
              stageKeys.slice(0, stageKeys.indexOf(stage)).forEach(s => next.add(s));
              return next;
            });
          }
        }
        if (msg.type === 'complete') {
          setDoneStages(new Set(stageKeys));
          setWsStatus('closed');
          onComplete({
            report:          msg.data,
            llm_insights:    msg.extras?.llm_insights    ?? {},
            recommendations: msg.extras?.recommendations ?? [],
            flights:         msg.extras?.flights         ?? [],
            hotels:          msg.extras?.hotels          ?? [],
          });
        }
        if (msg.type === 'error') {
          setLines(prev => [...prev, `❌ ERROR: ${msg.data}`]);
          setFatalError(true);
          setWsStatus('closed');
        }
      };

      ws.onerror = () => {
        if (cancelled) return;
        setLines(prev => {
          if (prev.length === 0) { setFatalError(true); return ['❌ Cannot connect to backend on port 8000']; }
          return prev;
        });
        setWsStatus('closed');
      };

      ws.onclose = () => { if (!cancelled) setWsStatus('closed'); };
    }, 50);

    return () => {
      cancelled = true;
      clearTimeout(timer);
      wsRef.current = null;
      ws?.close();
    };
  }, [sessionId, onComplete]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [lines]);

  return (
    <div className="max-w-5xl mx-auto space-y-4 animate-fade-in">
      {/* Progress card */}
      <div className="card-white workflow-card p-5 sm:p-6">
        <div className="flex items-center justify-between mb-3">
          <div>
            <p className="text-sm font-bold text-gray-800">AI Pipeline Progress</p>
            <p className="text-xs text-slate-500 mt-0.5">Agents run in sequence and stream their status live.</p>
          </div>
          <div className="flex items-center gap-2">
            <span className={`text-xs font-bold ${wsStatus === 'open' ? 'text-brand' : wsStatus === 'connecting' ? 'text-orange-500' : 'text-green-600'}`}>
              {wsStatus === 'open' ? 'Running…' : wsStatus === 'connecting' ? 'Connecting…' : '✓ Complete'}
            </span>
            <span className="text-xs text-gray-400 font-semibold bg-gray-100 px-2 py-0.5 rounded-full">{pct}%</span>
          </div>
        </div>

        <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden mb-5">
          <div className="h-full rounded-full transition-all duration-700"
            style={{ width: `${pct}%`, background: 'linear-gradient(to right, #003580, #16a34a)' }} />
        </div>

        {/* Stage grid */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {STAGES.map((stage) => {
            const done   = doneStages.has(stage.key);
            const active = activeStage === stage.key && !done && wsStatus !== 'closed';
            return (
              <div key={stage.key} className={`flex items-center gap-2.5 px-3 py-2.5 rounded-xl border transition-all ${
                done   ? `${stage.bg} ${stage.border}` :
                active ? `${stage.bg} ${stage.border}` :
                         'bg-gray-50 border-gray-100'
              }`}>
                <div className={`w-6 h-6 rounded-full border-2 flex items-center justify-center text-xs flex-shrink-0 font-bold ${
                  done   ? 'border-green-500 bg-green-500 text-white' :
                  active ? `${stage.border} bg-white ${stage.text}` :
                           'border-gray-200 text-gray-400'
                }`}>
                  {done ? '✓' : active ? <span className="animate-pulse">·</span> : stageKeys.indexOf(stage.key) + 1}
                </div>
                <p className={`text-xs font-semibold truncate ${done ? 'text-green-700' : active ? stage.text : 'text-gray-400'}`}>
                  {stage.icon} {stage.label}
                </p>
              </div>
            );
          })}
        </div>
      </div>

      {/* Live log */}
      <div className="card-white overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 bg-white/70">
          <p className="text-sm font-semibold text-gray-600">Live Agent Log</p>
          <div className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${
              wsStatus === 'open' ? 'bg-green-500 animate-pulse' :
              wsStatus === 'connecting' ? 'bg-yellow-500 animate-pulse' : 'bg-gray-300'
            }`} />
            <span className="text-xs text-gray-400 font-medium">
              {wsStatus === 'open' ? 'live' : wsStatus === 'connecting' ? 'connecting' : 'done'}
            </span>
          </div>
        </div>
        <div className="h-72 overflow-y-auto p-4 font-mono text-xs space-y-0.5 bg-slate-50/90">
          {lines.length === 0 && <p className="text-gray-400 animate-pulse py-2">Waiting for first agent event…</p>}
          {lines.map((line, i) => (
            <div key={i} className={`leading-5 ${lineColor(line)}`}>{line}</div>
          ))}
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
