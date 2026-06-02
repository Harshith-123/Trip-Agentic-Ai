import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'TravelSmart - AI-Powered Travel Savings',
  description: 'Find the best flights, hotels and credit card rewards with AI. Powered by LangGraph, Duffel API, and Groq.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen app-background text-text antialiased">{children}</body>
    </html>
  );
}
