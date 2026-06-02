'use client';

import { useRouter } from 'next/navigation';
import Image from 'next/image';
import {
  Plane, Hotel, Search, Star, Shield, Zap,
  TrendingDown, ChevronRight, CreditCard, Award, Globe
} from 'lucide-react';
import TripForm from '@/components/TripForm';

const DESTINATIONS = [
  { city: 'Dubai',     country: 'UAE',       img: 'https://images.unsplash.com/photo-1512453979798-5ea266f8880c?w=600&q=80&auto=format&fit=crop', flight: 'from $420', hotel: 'from $89/night',  tag: 'Popular',    tagClass: 'badge-brand' },
  { city: 'Paris',     country: 'France',    img: 'https://images.unsplash.com/photo-1502602898657-3e91760cbb34?w=600&q=80&auto=format&fit=crop', flight: 'from $580', hotel: 'from $120/night', tag: 'Trending',   tagClass: 'badge-orange' },
  { city: 'Singapore', country: 'Singapore', img: 'https://images.unsplash.com/photo-1525625293386-3f8f99389edd?w=600&q=80&auto=format&fit=crop', flight: 'from $340', hotel: 'from $95/night',  tag: 'Best Value', tagClass: 'badge-green' },
  { city: 'New York',  country: 'USA',       img: 'https://images.unsplash.com/photo-1496442226666-8d4d0e62e6e9?w=600&q=80&auto=format&fit=crop', flight: 'from $650', hotel: 'from $140/night', tag: 'Popular',    tagClass: 'badge-brand' },
  { city: 'Tokyo',     country: 'Japan',     img: 'https://images.unsplash.com/photo-1540959733332-eab4deabeeaf?w=600&q=80&auto=format&fit=crop', flight: 'from $490', hotel: 'from $75/night',  tag: 'Trending',   tagClass: 'badge-orange' },
  { city: 'Bali',      country: 'Indonesia', img: 'https://images.unsplash.com/photo-1537996194471-e657df975ab4?w=600&q=80&auto=format&fit=crop', flight: 'from $380', hotel: 'from $55/night',  tag: 'Best Value', tagClass: 'badge-green' },
];

const DEALS = [
  { icon: '✈️', title: 'Flash Sale: 30% off flights to Europe',  sub: 'Book by Sunday · Use code EURO30',       color: 'bg-blue-50 border-blue-200' },
  { icon: '🏨', title: 'Hotel Week: Extra 20% off 3+ nights',    sub: 'Select properties · Limited time',        color: 'bg-green-50 border-green-200' },
  { icon: '💳', title: 'Pay with HDFC Infinia - save up to 15%', sub: 'AI card optimizer finds your best card',  color: 'bg-purple-50 border-purple-200' },
];

const TRUST = [
  { icon: Shield, title: 'Best Price Guarantee', sub: 'We match any lower price you find' },
  { icon: Zap,    title: 'Live Fares via Duffel', sub: 'Real-time flight data, not cached' },
  { icon: Award,  title: 'AI Card Optimizer',     sub: '25+ cards analyzed for max savings' },
  { icon: Globe,  title: '15+ Platforms',          sub: 'Flights & hotels across the web' },
];

function DestCard({ d, onClick }: { d: typeof DESTINATIONS[0]; onClick: () => void }) {
  return (
    <div onClick={onClick} className="card-hover overflow-hidden group">
      <div className="relative h-44 overflow-hidden">
        <Image src={d.img} alt={d.city} fill
          className="object-cover group-hover:scale-105 transition-transform duration-500"
          sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 33vw" />
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent" />
        <div className="absolute top-3 left-3"><span className={d.tagClass}>{d.tag}</span></div>
        <div className="absolute bottom-3 left-3 text-white">
          <p className="font-bold text-lg leading-tight">{d.city}</p>
          <p className="text-xs text-white/80">{d.country}</p>
        </div>
      </div>
      <div className="p-4 flex items-center justify-between">
        <div className="flex gap-5">
          <div>
            <p className="text-xs text-gray-400 flex items-center gap-1 mb-0.5"><Plane size={10} /> Flights</p>
            <p className="text-sm font-bold text-brand">{d.flight}</p>
          </div>
          <div>
            <p className="text-xs text-gray-400 flex items-center gap-1 mb-0.5"><Hotel size={10} /> Hotels</p>
            <p className="text-sm font-bold text-green-600">{d.hotel}</p>
          </div>
        </div>
        <ChevronRight size={16} className="text-gray-300 group-hover:text-brand group-hover:translate-x-0.5 transition-all" />
      </div>
    </div>
  );
}

export default function Home() {
  const router = useRouter();

  return (
    <div className="app-background">

      {/* Nav */}
      <nav className="top-nav">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 flex items-center justify-between h-14">
          <div className="flex items-center gap-2">
            <div className="nav-brand-mark">
              <Plane size={17} />
            </div>
            <span className="text-white font-extrabold text-lg tracking-tight">TravelSmart</span>
            <span className="hidden sm:block text-cyan-100/70 text-xs ml-1">AI travel desk</span>
          </div>
          <div className="flex items-center gap-1">
            <button onClick={() => router.push('/agent')}
              className="text-white/80 hover:text-white hover:bg-white/10 text-sm font-medium px-3 py-1.5 rounded-xl transition-all flex items-center gap-1.5">
              <Zap size={14} /> AI Agent
            </button>
            <button onClick={() => router.push('/scraper')}
              className="text-white/80 hover:text-white hover:bg-white/10 text-sm font-medium px-3 py-1.5 rounded-xl transition-all flex items-center gap-1.5">
              <Search size={14} /> Quick Search
            </button>
            <a href="http://localhost:8000/docs" target="_blank" rel="noopener noreferrer"
              className="hidden sm:flex text-white/50 hover:text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-all items-center gap-1">
              API ↗
            </a>
          </div>
        </div>
      </nav>

      {/* ── Hero with embedded TripForm ── */}
      <section className="hero-bg relative">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-16 sm:py-20 flex flex-col lg:flex-row items-start gap-10">

          {/* Left - headline */}
          <div className="flex-1 pt-4 animate-fade-in">
            <div className="inline-flex items-center gap-2 bg-white/15 backdrop-blur-sm border border-white/20 rounded-full px-4 py-1.5 mb-6 shadow-lg shadow-black/10">
              <Star size={12} className="text-yellow-300 fill-yellow-300" />
              <span className="text-white text-xs font-semibold">AI itinerary desk · live fares · card savings</span>
            </div>
            <h1 className="text-4xl sm:text-6xl font-black text-white mb-5 leading-[0.98] tracking-tight drop-shadow-lg">
              Search less.<br />
              <span className="bg-gradient-to-r from-yellow-200 via-cyan-100 to-emerald-200 bg-clip-text text-transparent">Travel better.</span>
            </h1>
            <p className="text-white/85 text-base sm:text-lg max-w-xl leading-relaxed mb-8">
              Plan the trip, compare flights and hotels, then let the financial engine pick the card that actually lowers your effective cost.
            </p>
            {/* Trust pills */}
            <div className="flex flex-wrap gap-2">
              {['Trip setup', 'Live search', 'AI comparison', 'Savings report'].map(t => (
                <span key={t} className="bg-white/15 backdrop-blur-sm border border-white/20 text-white text-xs font-semibold px-3 py-1.5 rounded-full">
                  ✓ {t}
                </span>
              ))}
            </div>
          </div>

          {/* Right - TripForm card */}
          <div className="w-full lg:w-[480px] flex-shrink-0 animate-slide-up">
            <div className="glass-panel workflow-card overflow-hidden">
              <div className="bg-gradient-to-r from-brand via-sky-700 to-emerald-600 px-5 py-4 flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                <Zap size={15} className="text-yellow-300" />
                <span className="text-white font-bold text-sm">AI Agent - Find Best Deals</span>
                </div>
                <span className="rounded-full bg-white/15 px-2.5 py-1 text-[11px] font-bold uppercase tracking-widest text-white/80">Step 1</span>
              </div>
              <div className="p-4">
                <TripForm onStart={(sid) => router.push(`/agent?session=${sid}`)} />
              </div>
            </div>
          </div>

        </div>
      </section>

      {/* Workflow cards */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {DEALS.map((d, i) => (
            <div key={i} className={`workflow-card flex items-start gap-3 p-4 rounded-3xl border ${d.color} cursor-pointer hover:shadow-xl hover:-translate-y-0.5 transition-all`}>
              <span className="text-2xl flex-shrink-0">{d.icon}</span>
              <div>
                <p className="text-sm font-bold text-gray-800">{d.title}</p>
                <p className="text-xs text-gray-500 mt-0.5">{d.sub}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Popular Destinations */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 pb-10">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h2 className="text-xl font-extrabold text-gray-900">Popular Destinations</h2>
            <p className="text-sm text-gray-500 mt-0.5">Indicative prices · Search for live rates</p>
          </div>
          <button onClick={() => router.push('/agent')}
            className="text-brand text-sm font-semibold hover:underline flex items-center gap-1">
            Search all <ChevronRight size={14} />
          </button>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {DESTINATIONS.map(d => (
            <DestCard key={d.city} d={d} onClick={() => router.push('/agent')} />
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className="bg-white/70 border-y border-white/70 py-12 backdrop-blur">
        <div className="max-w-7xl mx-auto px-4 sm:px-6">
          <h2 className="text-2xl font-black text-gray-900 text-center mb-2">One Clean Workflow</h2>
          <p className="text-sm text-gray-500 text-center mb-8">Move from cards to trip setup to recommendations without leaving the flow.</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
            {[
              { step: '1', icon: CreditCard,  title: 'Add your cards',     desc: 'Enter your credit/debit cards. We only use the last 4 digits - never store full numbers.', bg: 'bg-blue-50',   color: 'text-brand' },
              { step: '2', icon: Search,       title: 'Search live prices', desc: 'AI fetches real-time flights from Duffel API and scrapes 11+ hotel platforms simultaneously.', bg: 'bg-green-50',  color: 'text-green-700' },
              { step: '3', icon: TrendingDown, title: 'Get your best deal', desc: 'The financial engine calculates effective cost per card and shows exactly how much you save.', bg: 'bg-purple-50', color: 'text-purple-700' },
            ].map(s => (
              <div key={s.step} className="workflow-card flex flex-col items-center text-center p-6 rounded-3xl bg-white/85 border border-white/80 shadow-sm shadow-slate-900/5">
                <div className={`w-12 h-12 rounded-2xl ${s.bg} ${s.color} flex items-center justify-center mb-4 shadow-sm`}>
                  <s.icon size={22} />
                </div>
                <div className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-1">Step {s.step}</div>
                <h3 className="text-base font-bold text-gray-900 mb-2">{s.title}</h3>
                <p className="text-sm text-gray-500 leading-relaxed">{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Trust badges */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 py-10">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {TRUST.map(t => (
            <div key={t.title} className="card-white p-5 flex flex-col items-center text-center">
              <div className="w-10 h-10 rounded-xl flex items-center justify-center mb-3" style={{ backgroundColor: 'rgba(0,53,128,0.08)' }}>
                <t.icon size={20} className="text-brand" />
              </div>
              <p className="text-sm font-bold text-gray-800 mb-1">{t.title}</p>
              <p className="text-xs text-gray-500">{t.sub}</p>
            </div>
          ))}
        </div>
      </section>

      {/* CTA Banner */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 pb-12">
        <div className="bg-gradient-to-r from-[#07172f] via-brand to-emerald-700 rounded-[2rem] p-8 sm:p-10 flex flex-col sm:flex-row items-center justify-between gap-6 relative overflow-hidden shadow-2xl shadow-brand/20">
          <div className="absolute inset-0 opacity-20" style={{ backgroundImage: 'radial-gradient(circle at 80% 50%, white 0%, transparent 60%)' }} />
          <div className="relative">
            <h2 className="text-2xl font-extrabold text-white mb-2">Ready to save on your next trip?</h2>
            <p className="text-white/70 text-sm">Let AI find your best flight, hotel, and card combination.</p>
          </div>
          <div className="flex gap-3 relative flex-shrink-0">
            <button onClick={() => router.push('/agent')}
              className="bg-white text-brand font-bold text-sm px-6 py-3 rounded-xl hover:bg-gray-50 transition-all shadow-lg flex items-center gap-2">
              <Zap size={15} /> Start AI Agent
            </button>
            <button onClick={() => router.push('/scraper')}
              className="bg-white/10 border border-white/30 text-white font-semibold text-sm px-5 py-3 rounded-xl hover:bg-white/20 transition-all flex items-center gap-2">
              <Search size={15} /> Quick Search
            </button>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-white border-t border-gray-100 py-8">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 bg-brand rounded-lg flex items-center justify-center">
              <Plane size={13} className="text-white" />
            </div>
            <span className="font-bold text-gray-800">TravelSmart</span>
            <span className="text-gray-400 text-xs">AI-Powered Travel Savings</span>
          </div>
          <div className="flex items-center gap-4 text-xs text-gray-400">
            <span>LangGraph · Duffel API · Groq · FastAPI · Next.js</span>
            <a href="http://localhost:8000/docs" target="_blank" rel="noopener noreferrer" className="text-brand hover:underline">API Docs ↗</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
