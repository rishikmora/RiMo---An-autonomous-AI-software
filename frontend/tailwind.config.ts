import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Operations console palette — deliberately not cream/acid-green/broadsheet.
        void: "#0A0B0F",
        panel: "#12141C",
        raised: "#1C1F2A",
        line: "#262A38",
        ink: "#E8EAF0",
        muted: "#6E7891",
        faint: "#454C61",
        signal: "#5B8CFF", // the "active / thinking" pulse
        // Role-coded accents for the agent floor
        role: {
          ceo: "#F2C14E",
          research: "#8B7FF5",
          planner: "#5B8CFF",
          architect: "#4EC3C1",
          builder: "#5FD17A",
          reviewer: "#F08A5D",
          qa: "#E36AA8",
          security: "#E5544B",
          devops: "#3FB4E8",
          memory: "#A0A6B8",
        },
        ok: "#5FD17A",
        warn: "#F2C14E",
        danger: "#E5544B",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      fontSize: {
        eyebrow: ["0.6875rem", { letterSpacing: "0.14em", lineHeight: "1" }],
      },
      borderRadius: { card: "14px", pill: "999px" },
      boxShadow: {
        panel: "0 1px 0 0 rgba(255,255,255,0.03) inset, 0 18px 40px -24px rgba(0,0,0,0.8)",
        glow: "0 0 0 1px rgba(91,140,255,0.35), 0 0 28px -6px rgba(91,140,255,0.5)",
      },
      keyframes: {
        breathe: {
          "0%,100%": { opacity: "0.35", transform: "scale(1)" },
          "50%": { opacity: "1", transform: "scale(1.18)" },
        },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        sweep: {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(300%)" },
        },
      },
      animation: {
        breathe: "breathe 1.8s ease-in-out infinite",
        "slide-up": "slide-up 0.35s cubic-bezier(0.2,0.7,0.2,1)",
        sweep: "sweep 2.2s linear infinite",
      },
    },
  },
  plugins: [],
};
export default config;
