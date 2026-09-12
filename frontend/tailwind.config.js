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
        // Deep space dark background palette
        surface: {
          900: "#050714",
          800: "#0b1021",
          700: "#131b33",
          600: "#1a2544",
          500: "#223055",
        },
        // Neon Cyan
        brand: {
          50:  "#e0fbfc",
          100: "#b5f3fa",
          200: "#83e8f7",
          300: "#4cdbf2",
          400: "#27cbeb",
          500: "#00b4d8",
          600: "#0090b8",
          700: "#007396",
          800: "#005a78",
          900: "#00455c",
        },
        // Electric Purple/Pink
        accent: {
          300: "#e5b3fe",
          400: "#d08afc",
          500: "#b95cf9",
          600: "#9d3ae1",
          700: "#8022c4",
        },
      },
      fontFamily: {
        sans: ["Outfit", "Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
      backgroundImage: {
        "gradient-radial": "radial-gradient(circle at center, var(--tw-gradient-stops))",
        "card-shine": "linear-gradient(135deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0) 100%)",
        "glass-gradient": "linear-gradient(135deg, rgba(255, 255, 255, 0.05) 0%, rgba(255, 255, 255, 0.01) 100%)",
      },
      animation: {
        "fade-in": "fadeIn 0.3s ease-out forwards",
        "slide-up": "slideUp 0.4s ease-out forwards",
        "blob": "blob 7s infinite",
        "shimmer": "shimmer 2s infinite linear",
        "float": "float 6s ease-in-out infinite",
        "pulse-slow": "pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(20px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        blob: {
          "0%": { transform: "translate(0px, 0px) scale(1)" },
          "33%": { transform: "translate(30px, -50px) scale(1.1)" },
          "66%": { transform: "translate(-20px, 20px) scale(0.9)" },
          "100%": { transform: "translate(0px, 0px) scale(1)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-10px)" },
        }
      },
      boxShadow: {
        "glow-brand": "0 0 25px rgba(0, 180, 216, 0.4)",
        "glow-accent": "0 0 25px rgba(185, 92, 249, 0.4)",
        "glass": "0 8px 32px 0 rgba(0, 0, 0, 0.37)",
        "glass-inset": "inset 0 1px 1px 0 rgba(255, 255, 255, 0.1), 0 8px 32px 0 rgba(0, 0, 0, 0.3)",
      },
    },
  },
  plugins: [],
}
