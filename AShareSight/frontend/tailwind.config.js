/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontSize: {
        '2xs': ['11px', { lineHeight: '16px' }],
      },
      colors: {
        ash: {
          bg: 'var(--ash-bg)',
          'bg-secondary': 'var(--ash-bg-secondary)',
          card: 'var(--ash-card)',
          panel: 'var(--ash-panel)',
          border: 'var(--ash-border)',
          hover: 'var(--ash-hover)',
          text: 'var(--ash-text)',
          'text-secondary': 'var(--ash-text-secondary)',
          muted: 'var(--ash-muted)',
          primary: 'rgb(var(--ash-primary) / <alpha-value>)',
          up: 'var(--ash-up)',
          down: 'var(--ash-down)',
          warning: 'var(--ash-warning)',
          predict: 'var(--ash-predict)',
        },
        fin: {
          bg: 'var(--ash-bg)',
          'bg-secondary': 'var(--ash-bg-secondary)',
          card: 'var(--ash-card)',
          panel: 'var(--ash-panel)',
          border: 'var(--ash-border)',
          hover: 'var(--ash-hover)',
          text: 'var(--ash-text)',
          'text-secondary': 'var(--ash-text-secondary)',
          muted: 'var(--ash-muted)',
          primary: 'rgb(var(--ash-primary) / <alpha-value>)',
          success: 'var(--ash-up)',
          danger: 'var(--ash-down)',
          warning: 'var(--ash-warning)',
          predict: 'var(--ash-predict)',
        },
        trend: {
          up: 'var(--ash-up)',
          down: 'var(--ash-down)',
        }
      },
      fontFamily: {
        sans: ['-apple-system', '"PingFang SC"', '"Microsoft YaHei"', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-up': 'slideUp 0.4s ease-out',
        'slide-in-right': 'slideInRight 0.3s ease-out',
        'fade-out': 'fadeOut 0.25s ease-in forwards',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { transform: 'translateY(20px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        slideInRight: {
          '0%': { transform: 'translateX(100%)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        fadeOut: {
          '0%': { opacity: '1', transform: 'translateX(0)' },
          '100%': { opacity: '0', transform: 'translateX(30%)' },
        },
      }
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
