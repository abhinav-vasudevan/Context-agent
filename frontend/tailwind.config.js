/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: "class",
  theme: {
      extend: {
          colors: {
              nude: {
                  900: '#fafaf9', // Lightest (background)
                  850: '#f5f5f4', // Off-white (panels)
                  800: '#e7e5e4', // Warm Beige (borders)
                  700: '#d6d3d1', // Light gray/taupe
                  600: '#a8a29e', // Muted 
                  500: '#78716c', // Mid-tone
                  400: '#57534e', // Muted text
                  300: '#44403c', // Main text
                  200: '#292524', // Highlighted text
                  100: '#231f1c', // Very dark 
                  50: '#1c1917',  // Darkest
              },
              primary: '#44403c',
              accent: {
                  DEFAULT: '#8b7b6c', // Darker warm accent for light bg
                  hover: '#736457',
              }
          },
          borderRadius: {
              "DEFAULT": "0.25rem",
              "md": "0.375rem",
              "lg": "0.5rem",
              "xl": "0.75rem",
              "2xl": "1rem",
              "full": "9999px"
          },
          fontFamily: {
              "sans": ["Inter", "system-ui", "sans-serif"],
              "mono": ["JetBrains Mono", "Fira Code", "monospace"]
          },
          boxShadow: {
              'soft': '0 4px 20px -2px rgba(0, 0, 0, 0.08)',
              'inner-soft': 'inset 0 2px 4px 0 rgba(0, 0, 0, 0.05)'
          }
      },
  },
  plugins: [],
}
