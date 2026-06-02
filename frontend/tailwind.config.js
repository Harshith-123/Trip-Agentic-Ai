/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  safelist: [
    'badge-brand', 'badge-green', 'badge-orange',
    'text-blue-600', 'text-orange-500', 'text-green-600', 'text-purple-600', 'text-yellow-600',
    'bg-blue-50', 'bg-orange-50', 'bg-green-50', 'bg-purple-50', 'bg-yellow-50',
  ],
  theme: {
    extend: {
      colors: {
        brand:        '#003580',
        'brand-dark': '#002a66',
        'brand-light':'#e8f0fe',
        bg:           '#f0f4f8',
        surface:      '#ffffff',
        border:       '#e2e8f0',
        success:      '#16a34a',
        warning:      '#d97706',
        danger:       '#dc2626',
        muted:        '#6b7280',
        text:         '#1a202c',
        subtle:       '#4b5563',
      },
      fontFamily: {
        sans: ['Inter', 'Segoe UI', 'system-ui', '-apple-system', 'sans-serif'],
      },
      boxShadow: {
        'card':       '0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04)',
        'card-hover': '0 4px 12px rgba(0,0,0,0.12), 0 2px 4px rgba(0,0,0,0.06)',
        'search':     '0 8px 32px rgba(0,0,0,0.18)',
      },
      animation: {
        'fade-in':  'fadeIn 0.35s ease-out',
        'slide-up': 'slideUp 0.35s ease-out',
        'shimmer':  'shimmer 1.5s infinite',
      },
      keyframes: {
        fadeIn:  { from: { opacity: '0' }, to: { opacity: '1' } },
        slideUp: { from: { opacity: '0', transform: 'translateY(12px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        shimmer: { from: { backgroundPosition: '-200% 0' }, to: { backgroundPosition: '200% 0' } },
      },
    },
  },
  plugins: [],
};
