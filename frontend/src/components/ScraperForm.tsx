'use client';

import { useState } from 'react';
import { MapPin, Calendar, Users, DollarSign } from 'lucide-react';
import { apiUrl } from '@/lib/api';
import { AIRPORT_OPTIONS, airportCode } from '@/lib/options';

interface Props { onStart: (sessionId: string) => void; }

const CURRENCIES = ['USD', 'INR', 'EUR', 'GBP', 'AED', 'SGD', 'AUD', 'CAD', 'JPY'];

function today()        { return new Date().toISOString().split('T')[0]; }
function daysLater(n: number) { const d = new Date(); d.setDate(d.getDate() + n); return d.toISOString().split('T')[0]; }

export default function ScraperForm({ onStart }: Readonly<Props>) {
  const [origin,      setOrigin]      = useState('');
  const [destination, setDestination] = useState('');
  const [tripType,    setTripType]    = useState<'one-way' | 'round-trip'>('round-trip');
  const [date,        setDate]        = useState(today());
  const [returnDate,  setReturnDate]  = useState(daysLater(7));
  const [city,        setCity]        = useState('');
  const [checkIn,     setCheckIn]     = useState(daysLater(1));
  const [checkOut,    setCheckOut]    = useState(daysLater(8));
  const [adults,      setAdults]      = useState(1);
  const [currency,    setCurrency]    = useState('USD');
  const [error,       setError]       = useState('');
  const [loading,     setLoading]     = useState(false);

  async function submit() {
    const org = airportCode(origin), dst = airportCode(destination);
    if (!org || !dst || !date)                    { setError('Fill in origin, destination and departure date.'); return; }
    if (org === dst)                              { setError('Origin and destination cannot be the same.'); return; }
    if (org.length !== 3 || dst.length !== 3)    { setError('Airport codes must be 3 letters (e.g. DEL, JFK).'); return; }
    if (!city.trim())                             { setError('Enter a hotel city name (e.g. New York, Dubai).'); return; }
    if (!checkIn || !checkOut)                    { setError('Fill in hotel check-in and check-out dates.'); return; }
    if (checkOut <= checkIn)                      { setError('Check-out must be after check-in.'); return; }
    if (tripType === 'round-trip' && !returnDate) { setError('Select a return date.'); return; }
    setError(''); setLoading(true);
    try {
      const res = await fetch(apiUrl('/api/scrape/run'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          origin: org, destination: dst, date, city: city.trim(),
          check_in: checkIn, check_out: checkOut, adults, currency,
          trip_type: tripType, return_date: tripType === 'round-trip' ? returnDate : '',
        }),
      });
      const data = await res.json();
      if (data.error) { setError(data.error); setLoading(false); return; }
      onStart(data.session_id);
    } catch {
      setError('Network error - is the backend running on port 8000?');
      setLoading(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-4 animate-slide-up">
      <datalist id="scraper-airport-options">
        {AIRPORT_OPTIONS.map(airport => (
          <option key={airport.code} value={airport.code}>{airport.label}</option>
        ))}
      </datalist>

      {/* Trip type */}
      <div className="card-white p-1.5 flex gap-1">
        {(['one-way', 'round-trip'] as const).map((t) => (
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
            <input className="input-field uppercase font-mono tracking-widest text-base font-bold" list="scraper-airport-options" placeholder="DEL"
              value={origin} maxLength={3} onChange={(e) => setOrigin(airportCode(e.target.value))} />
          </div>
          <div>
            <label className="label-sm">Destination (IATA)</label>
            <input className="input-field uppercase font-mono tracking-widest text-base font-bold" list="scraper-airport-options" placeholder="DXB"
              value={destination} maxLength={3} onChange={(e) => setDestination(airportCode(e.target.value))} />
          </div>
          <div>
            <label className="label-sm"><Calendar size={10} className="inline mr-1" />Departure</label>
            <input type="date" className="input-field" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
          <div>
            <label className="label-sm"><Calendar size={10} className="inline mr-1" />Return</label>
            <input type="date" className="input-field disabled:opacity-30 disabled:cursor-not-allowed"
              value={returnDate} disabled={tripType === 'one-way'} onChange={(e) => setReturnDate(e.target.value)} />
          </div>
        </div>
      </div>

      {/* Hotel */}
      <div className="card-white workflow-card p-5">
        <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-4">🏨 Hotel Details</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="label-sm">City Name</label>
            <input className="input-field" placeholder="e.g. Dubai, New York, Singapore"
              value={city} onChange={(e) => setCity(e.target.value)} />
          </div>
          <div>
            <label className="label-sm"><Calendar size={10} className="inline mr-1" />Check-In</label>
            <input type="date" className="input-field" value={checkIn} onChange={(e) => setCheckIn(e.target.value)} />
          </div>
          <div>
            <label className="label-sm"><Calendar size={10} className="inline mr-1" />Check-Out</label>
            <input type="date" className="input-field" value={checkOut} onChange={(e) => setCheckOut(e.target.value)} />
          </div>
        </div>
      </div>

      {/* Preferences */}
      <div className="card-white workflow-card p-5">
        <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-4">Preferences</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="label-sm"><Users size={10} className="inline mr-1" />Adults</label>
            <input type="number" className="input-field" min={1} max={9} value={adults}
              onChange={(e) => setAdults(Number(e.target.value))} />
          </div>
          <div>
            <label className="label-sm"><DollarSign size={10} className="inline mr-1" />Currency</label>
            <select className="input-field" value={currency} onChange={(e) => setCurrency(e.target.value)}>
              {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
        </div>
      </div>

      {error && <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-600">{error}</div>}

      <button onClick={submit} disabled={loading}
        className="btn-brand w-full flex items-center justify-center gap-2 py-4 text-base">
        {loading ? <><span className="animate-spin inline-block text-lg">⟳</span> Starting Scraper…</> : '⚡ Scrape All Platforms'}
      </button>
    </div>
  );
}
