'use client';

import { useState, useEffect } from 'react';
import { CreditCard, MapPin, Calendar, Users, DollarSign, Trash2, Plus } from 'lucide-react';
import { apiUrl } from '@/lib/api';
import { AIRPORT_OPTIONS, BANK_OPTIONS, CARD_OPTIONS, airportCode, findCardOption } from '@/lib/options';

interface Card {
  name: string; bank: string; network: string; card_type: string; number_last4: string;
}
interface Props { onStart: (sessionId: string) => void; }

const NETWORKS  = ['visa', 'mastercard', 'amex', 'rupay', 'diners'];
const CURRENCIES = ['USD', 'INR', 'EUR', 'GBP', 'AED', 'SGD', 'AUD', 'CAD', 'JPY'];
const NET_COLORS: Record<string, string> = {
  visa: 'text-blue-600', mastercard: 'text-orange-500',
  amex: 'text-green-600', rupay: 'text-purple-600', diners: 'text-yellow-600',
};
const NET_BG: Record<string, string> = {
  visa: 'bg-blue-50', mastercard: 'bg-orange-50',
  amex: 'bg-green-50', rupay: 'bg-purple-50', diners: 'bg-yellow-50',
};

function today()        { return new Date().toISOString().split('T')[0]; }
function daysLater(n: number) { const d = new Date(); d.setDate(d.getDate() + n); return d.toISOString().split('T')[0]; }
function daysFromDate(dateStr: string, n: number) {
  try { const d = new Date(dateStr); d.setDate(d.getDate() + n); return d.toISOString().split('T')[0]; }
  catch { return dateStr; }
}

export default function TripForm({ onStart }: Props) {
  const [step, setStep]       = useState<1 | 2>(1);
  const [cards, setCards]     = useState<Card[]>([]);
  const [cardForm, setCardForm] = useState<Card>({ name: '', bank: '', network: 'visa', card_type: 'credit', number_last4: '' });
  const [tripType, setTripType] = useState<'one-way' | 'round-trip'>('round-trip');
  const [origin, setOrigin]   = useState('');
  const [dest, setDest]       = useState('');
  const [checkIn, setCheckIn] = useState(today());
  const [retDate, setRetDate] = useState(daysLater(7));
  const [adults, setAdults]   = useState(1);
  const [currency, setCurrency] = useState('USD');
  const [hotelIn, setHotelIn]   = useState(daysLater(1));
  const [hotelOut, setHotelOut] = useState(daysLater(7));
  const [error, setError]     = useState('');
  const [loading, setLoading] = useState(false);

  // Keep hotel dates in sync with flight dates unless user has manually changed them
  useEffect(() => {
    setHotelIn(daysFromDate(checkIn, 1));
  }, [checkIn]);

  useEffect(() => {
    if (tripType === 'round-trip') setHotelOut(retDate);
  }, [retDate, tripType]);

  function addCard() {
    const { name, bank, number_last4 } = cardForm;
    if (!name.trim() || !bank.trim() || !number_last4.trim()) { setError('Card name, bank and last 4 digits are required.'); return; }
    if (!/^\d{4}$/.test(number_last4)) { setError('Last 4 digits must be exactly 4 numbers.'); return; }
    setCards(p => [...p, { ...cardForm, name: name.trim(), bank: bank.trim() }]);
    setCardForm({ name: '', bank: '', network: 'visa', card_type: 'credit', number_last4: '' });
    setError('');
  }

  function updateCardName(value: string) {
    const selected = findCardOption(value);
    setCardForm(p => ({
      ...p,
      name: value,
      bank: selected?.bank ?? p.bank,
      network: selected?.network ?? p.network,
    }));
  }

  async function submit() {
    const org = airportCode(origin), dst = airportCode(dest);
    if (!org || !dst || !checkIn)                          { setError('Fill in origin, destination and departure date.'); return; }
    if (org === dst)                                       { setError('Origin and destination cannot be the same.'); return; }
    if (org.length !== 3 || dst.length !== 3)             { setError('Airport codes must be 3 letters (e.g. BLR, JFK).'); return; }
    if (tripType === 'round-trip' && retDate <= checkIn)  { setError('Return date must be after departure.'); return; }
    if (!hotelIn || !hotelOut)                            { setError('Fill in both hotel dates.'); return; }
    if (hotelOut <= hotelIn)                              { setError('Hotel check-out must be after check-in.'); return; }
    if (!cards.length)                                    { setError('Add at least one card.'); return; }
    setError(''); setLoading(true);
    try {
      const res = await fetch(apiUrl('/api/run'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cards, origin: org, destination: dst,
          check_in: checkIn, check_out: tripType === 'round-trip' ? retDate : checkIn,
          trip_type: tripType, return_date: tripType === 'round-trip' ? retDate : '',
          hotel_check_in: hotelIn, hotel_check_out: hotelOut,
          adults, currency,
        }),
      });
      const data = await res.json();
      if (data.error) { setError(data.error); setLoading(false); return; }
      onStart(data.session_id);
    } catch {
      setError('Network error - is the backend running? (uvicorn api.server:app)');
      setLoading(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-4 animate-slide-up">
      <datalist id="card-options">
        {CARD_OPTIONS.map(card => (
          <option key={card.name} value={card.name}>{card.bank} · {card.network.toUpperCase()}</option>
        ))}
      </datalist>
      <datalist id="bank-options">
        {BANK_OPTIONS.map(bank => <option key={bank} value={bank} />)}
      </datalist>
      <datalist id="airport-options">
        {AIRPORT_OPTIONS.map(airport => (
          <option key={airport.code} value={airport.code}>{airport.label}</option>
        ))}
      </datalist>
      {/* Step tabs */}
      <div className="card-white p-1.5 flex gap-1">
        {([1, 2] as const).map((s) => (
          <button key={s}
            onClick={() => { if (s === 2 && !cards.length) { setError('Add at least one card first.'); return; } setError(''); setStep(s); }}
            className={`flex-1 flex items-center justify-center gap-2 text-sm font-semibold py-3 rounded-2xl transition-all ${
              step === s ? 'bg-gradient-to-r from-brand to-emerald-600 text-white shadow-sm' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
            }`}>
            <span className={`w-5 h-5 rounded-full border-2 flex items-center justify-center text-xs font-bold ${
              step === s ? 'border-white text-white' : s < step ? 'border-green-500 bg-green-500 text-white' : 'border-gray-300 text-gray-400'
            }`}>
              {s < step ? '✓' : s}
            </span>
            {s === 1 ? 'Your Cards' : 'Trip Details'}
          </button>
        ))}
      </div>

      {/* ── Step 1: Cards ── */}
      {step === 1 && (
        <div className="space-y-3">
          {cards.length > 0 && (
            <div className="space-y-2">
              {cards.map((c, i) => (
                <div key={i} className="card-white px-4 py-3 flex items-center gap-3 group">
                  <div className={`w-10 h-10 rounded-xl ${NET_BG[c.network] ?? 'bg-gray-50'} flex items-center justify-center flex-shrink-0`}>
                    <CreditCard size={18} className={NET_COLORS[c.network] ?? 'text-gray-500'} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-bold text-gray-800">{c.name}</p>
                    <p className="text-xs text-gray-400">{c.bank} · <span className={NET_COLORS[c.network] ?? ''}>{c.network.toUpperCase()}</span> · {c.card_type}</p>
                  </div>
                  <span className="font-mono text-xs text-brand border px-2.5 py-1 rounded-lg" style={{backgroundColor:'rgba(0,53,128,0.08)',borderColor:'rgba(0,53,128,0.2)'}}>•••• {c.number_last4}</span>
                  <button onClick={() => setCards(p => p.filter((_, idx) => idx !== i))}
                    className="opacity-100 sm:opacity-0 group-hover:opacity-100 text-gray-300 hover:text-red-500 transition-all p-1 rounded-lg">
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Add card form */}
          <div className="card-white workflow-card p-5 space-y-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-sm font-bold text-gray-800 flex items-center gap-2">
                  <Plus size={16} className="text-brand" /> Add a Card
                </p>
                <p className="text-xs text-slate-500 mt-1">Only the last 4 digits are used for identification.</p>
              </div>
              <span className="rounded-full bg-brand/10 px-3 py-1 text-[11px] font-bold uppercase tracking-widest text-brand">Secure</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className="label-sm">Card Name</label>
                <input className="input-field" list="card-options" placeholder="Start typing: HDFC Infinia, Amex Platinum..." value={cardForm.name}
                  onChange={e => updateCardName(e.target.value)} />
              </div>
              <div>
                <label className="label-sm">Bank</label>
                <input className="input-field" list="bank-options" placeholder="e.g. HDFC, Chase" value={cardForm.bank}
                  onChange={e => setCardForm(p => ({ ...p, bank: e.target.value }))} />
              </div>
              <div>
                <label className="label-sm">Last 4 Digits</label>
                <input className="input-field font-mono tracking-widest" placeholder="1234" maxLength={4} value={cardForm.number_last4}
                  onChange={e => setCardForm(p => ({ ...p, number_last4: e.target.value }))} />
              </div>
              <div>
                <label className="label-sm">Network</label>
                <select className="input-field" value={cardForm.network}
                  onChange={e => setCardForm(p => ({ ...p, network: e.target.value }))}>
                  {NETWORKS.map(n => <option key={n} value={n}>{n.charAt(0).toUpperCase() + n.slice(1)}</option>)}
                </select>
              </div>
              <div>
                <label className="label-sm">Type</label>
                <select className="input-field" value={cardForm.card_type}
                  onChange={e => setCardForm(p => ({ ...p, card_type: e.target.value }))}>
                  <option value="credit">Credit</option>
                  <option value="debit">Debit</option>
                </select>
              </div>
            </div>
            <button onClick={addCard}
            className="w-full border-2 border-dashed border-gray-200 hover:border-brand text-gray-400 hover:text-brand text-sm font-semibold py-3 rounded-2xl transition-all flex items-center justify-center gap-2 bg-white/60">
              <Plus size={15} /> Add Card
            </button>
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-600">{error}</div>
          )}

          <button onClick={() => { if (!cards.length) { setError('Add at least one card.'); return; } setError(''); setStep(2); }}
            className="btn-brand w-full flex items-center justify-center gap-2">
            Continue to Trip Details →
          </button>
        </div>
      )}

      {/* ── Step 2: Trip ── */}
      {step === 2 && (
        <div className="space-y-4">
          {/* Trip type */}
          <div className="card-white p-1.5 flex gap-1">
            {(['one-way', 'round-trip'] as const).map(t => (
              <button key={t} onClick={() => setTripType(t)}
                className={`flex-1 text-sm font-semibold py-3 rounded-2xl transition-all ${
                  tripType === t ? 'bg-gradient-to-r from-brand to-emerald-600 text-white shadow-sm' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
                }`}>
                {t === 'one-way' ? '✈️ One-Way' : '🔄 Round-Trip'}
              </button>
            ))}
          </div>

          {/* Flight */}
          <div className="card-white workflow-card p-5">
            <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-4 flex items-center gap-1.5">
              <MapPin size={12} /> Flight Details
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="label-sm">Origin (IATA)</label>
                <input className="input-field uppercase font-mono tracking-widest text-base font-bold" list="airport-options" placeholder="BLR"
                  value={origin} onChange={e => setOrigin(airportCode(e.target.value))} maxLength={3} />
              </div>
              <div>
                <label className="label-sm">Destination (IATA)</label>
                <input className="input-field uppercase font-mono tracking-widest text-base font-bold" list="airport-options" placeholder="JFK"
                  value={dest} onChange={e => setDest(airportCode(e.target.value))} maxLength={3} />
              </div>
              <div>
                <label className="label-sm"><Calendar size={10} className="inline mr-1" />Departure</label>
                <input type="date" className="input-field" value={checkIn} onChange={e => setCheckIn(e.target.value)} />
              </div>
              <div>
                <label className="label-sm"><Calendar size={10} className="inline mr-1" />Return</label>
                <input type="date" className="input-field disabled:opacity-30 disabled:cursor-not-allowed"
                  value={retDate} disabled={tripType === 'one-way'} onChange={e => setRetDate(e.target.value)} />
              </div>
              <div>
                <label className="label-sm"><Users size={10} className="inline mr-1" />Adults</label>
                <input type="number" className="input-field" min={1} max={9} value={adults}
                  onChange={e => setAdults(Number(e.target.value))} />
              </div>
              <div>
                <label className="label-sm"><DollarSign size={10} className="inline mr-1" />Currency</label>
                <select className="input-field" value={currency} onChange={e => setCurrency(e.target.value)}>
                  {CURRENCIES.map(c => <option key={c}>{c}</option>)}
                </select>
              </div>
            </div>
          </div>

          {/* Hotel */}
          <div className="card-white workflow-card p-5">
            <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-1 flex items-center gap-1.5">
              🏨 Hotel Dates
            </p>
            <p className="text-xs text-slate-400 mb-4">Pre-filled with your estimated arrival day — adjust if your flight takes longer.</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="label-sm"><Calendar size={10} className="inline mr-1" />Check-in (arrival day)</label>
                <input type="date" className="input-field" value={hotelIn} onChange={e => setHotelIn(e.target.value)} />
              </div>
              <div>
                <label className="label-sm"><Calendar size={10} className="inline mr-1" />Check-out</label>
                <input type="date" className="input-field" value={hotelOut} onChange={e => setHotelOut(e.target.value)} />
              </div>
            </div>
          </div>

          {error && <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-600">{error}</div>}

          <button onClick={submit} disabled={loading}
            className="btn-brand w-full flex items-center justify-center gap-2 py-4 text-base">
            {loading ? <><span className="animate-spin inline-block text-lg">⟳</span> Starting AI Agents…</> : '🚀 Find Best Deals + Optimize Cards'}
          </button>
        </div>
      )}
    </div>
  );
}
