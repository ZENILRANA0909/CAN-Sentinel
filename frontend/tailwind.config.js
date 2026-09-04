/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Surfaces: a cool, near-black stack that keeps long tables readable.
        base: {
          950: '#05080f',
          900: '#0a0f18',
          850: '#0e1420',
          800: '#131a28',
          700: '#1b2434',
          600: '#273245',
          500: '#35435c',
        },
        ink: {
          DEFAULT: '#e6ecf5',
          muted: '#93a3bb',
          faint: '#61708a',
        },
        accent: {
          DEFAULT: '#38bdf8',
          soft: '#0ea5e9',
          deep: '#0369a1',
        },
        severity: {
          info: '#64748b',
          low: '#38bdf8',
          medium: '#f0b429',
          high: '#f97316',
          critical: '#ef4444',
        },
        state: {
          ok: '#22c55e',
          warn: '#f0b429',
          bad: '#ef4444',
          idle: '#64748b',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      boxShadow: {
        panel: '0 1px 2px rgba(0,0,0,0.4), 0 8px 24px -12px rgba(0,0,0,0.6)',
        glow: '0 0 0 1px rgba(56,189,248,0.25), 0 0 24px -6px rgba(56,189,248,0.35)',
      },
      backgroundImage: {
        'panel-sheen': 'linear-gradient(180deg, rgba(255,255,255,0.035) 0%, rgba(255,255,255,0) 60%)',
        'grid-faint':
          'linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)',
      },
      keyframes: {
        'pulse-ring': {
          '0%': { boxShadow: '0 0 0 0 rgba(239,68,68,0.45)' },
          '70%': { boxShadow: '0 0 0 8px rgba(239,68,68,0)' },
          '100%': { boxShadow: '0 0 0 0 rgba(239,68,68,0)' },
        },
        'row-flash': {
          '0%': { backgroundColor: 'rgba(239,68,68,0.22)' },
          '100%': { backgroundColor: 'transparent' },
        },
      },
      animation: {
        'pulse-ring': 'pulse-ring 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'row-flash': 'row-flash 1.6s ease-out 1',
      },
    },
  },
  plugins: [],
}
