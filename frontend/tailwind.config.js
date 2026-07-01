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
                  900: '#1c1917', // Very dark stone (background)
                  850: '#231f1c', // Dark stone (panels)
                  800: '#292524', // Medium dark stone
                  700: '#44403c', // Cocoa/Taupe (borders, interactive surfaces)
                  600: '#57534e', // Lighter Taupe
                  500: '#78716c', // Mid-tone
                  400: '#a8a29e', // Muted text
                  300: '#d6d3d1', // Main text
                  200: '#e7e5e4', // Warm Beige (highlighted text)
                  100: '#f5f5f4', // Off-white
                  50: '#fafaf9',  // Pure off-white
              },
              primary: '#d6d3d1',
              accent: {
                  DEFAULT: '#b4a697', // Soft warm nude accent
                  hover: '#c6baae',
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
              'soft': '0 4px 20px -2px rgba(0, 0, 0, 0.4)',
              'inner-soft': 'inset 0 2px 4px 0 rgba(0, 0, 0, 0.2)'
          }
      },
  },
  plugins: [],
}
