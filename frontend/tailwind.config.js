/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{vue,ts,js,tsx,jsx}"],
  theme: {
    extend: {
      // Map CSS vars from src/style.css into Tailwind's color palette so
      // existing classes like ``bg-card`` / ``text-ink-2`` work without
      // hand-rolling style attrs.
      colors: {
        "bg-outer": "var(--bg-outer)",
        "bg-inner": "var(--bg-inner)",
        card: "var(--card)",
        "card-2": "var(--card-2)",
        "card-white": "var(--card-white)",
        ink: "var(--ink)",
        "ink-2": "var(--ink-2)",
        "ink-3": "var(--ink-3)",
        "ink-4": "var(--ink-4)",
        line: "var(--line)",
        "line-2": "var(--line-2)",
        primary: "var(--primary)",
        "primary-soft": "var(--primary-soft)",
        "primary-deep": "var(--primary-deep)",
        yellow: "var(--yellow)",
        "yellow-soft": "var(--yellow-soft)",
        green: "var(--green)",
        red: "var(--red)",
        dark: "var(--dark)",
        "dark-2": "var(--dark-2)",
      },
      borderRadius: {
        card: "var(--radius-card)",
        inner: "var(--radius-inner)",
        pill: "var(--radius-pill)",
      },
      fontFamily: {
        display: [
          "Plus Jakarta Sans", "Noto Sans SC",
          "ui-sans-serif", "system-ui", "sans-serif",
        ],
        "serif-cn": ["Noto Serif SC", "serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
