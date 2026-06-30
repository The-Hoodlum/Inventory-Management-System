/** @type {import('tailwindcss').Config} */
//
// ──────────────────────────────────────────────────────────────────────────
//  ERP DESIGN TOKENS  (single source of truth — see frontend/MODULE_GUIDE.md)
// ──────────────────────────────────────────────────────────────────────────
//  Components must NEVER hard-code colors. Use the semantic tokens below:
//
//    bg-canvas      app background          text-content        primary text
//    bg-surface     cards / panels          text-muted          secondary text
//    bg-elevated    popovers / menus        text-subtle         tertiary / hints
//    border-line    hairline borders        text-on-brand       text on brand fill
//    border-strong  stronger dividers
//    bg-brand-600   primary action          ring-brand-500      focus ring
//
//  Semantic colors are backed by CSS variables (see src/index.css) so the SAME
//  class works in light and dark — flip the `.dark` class on <html> to retheme.
//  `brand` (indigo) and `ink` (deep navy chrome) are fixed brand colors.
//
//  Scale tokens: radius (rounded-card / rounded-pill), shadow (shadow-card /
//  shadow-pop / shadow-sidebar), and the `2xs` font size for dense tables.
//
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Fixed brand — confident indigo, deliberate (not the default flat blue).
        brand: {
          50: "#eef2ff",
          100: "#e0e7ff",
          200: "#c7d2fe",
          300: "#a5b4fc",
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
          800: "#3730a3",
          900: "#312e81",
        },
        // Deep navy chrome (sidebar / launcher), constant across themes.
        ink: {
          950: "#0a0f1d",
          900: "#0f172a",
          800: "#1e293b",
          700: "#334155",
        },
        // Semantic, theme-aware tokens (resolved from CSS vars in index.css).
        canvas: "rgb(var(--canvas) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        elevated: "rgb(var(--elevated) / <alpha-value>)",
        content: {
          DEFAULT: "rgb(var(--content) / <alpha-value>)",
          muted: "rgb(var(--content-muted) / <alpha-value>)",
          subtle: "rgb(var(--content-subtle) / <alpha-value>)",
        },
        line: {
          DEFAULT: "rgb(var(--line) / <alpha-value>)",
          strong: "rgb(var(--line-strong) / <alpha-value>)",
        },
      },
      textColor: {
        // Convenience aliases so `text-muted` / `text-subtle` read naturally.
        muted: "rgb(var(--content-muted) / <alpha-value>)",
        subtle: "rgb(var(--content-subtle) / <alpha-value>)",
        "on-brand": "#ffffff",
      },
      borderColor: {
        DEFAULT: "rgb(var(--line) / <alpha-value>)",
        strong: "rgb(var(--line-strong) / <alpha-value>)",
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
        display: ["1.75rem", { lineHeight: "2.125rem", letterSpacing: "-0.01em" }],
      },
      borderRadius: {
        card: "0.875rem",
        pill: "9999px",
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.06)",
        pop: "0 12px 32px -12px rgb(15 23 42 / 0.30)",
        sidebar: "inset -1px 0 0 0 rgb(15 23 42 / 0.06)",
      },
      transitionDuration: {
        DEFAULT: "150ms",
      },
    },
  },
  plugins: [],
};
