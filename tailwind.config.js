/** Compiles static/src/input.css -> static/css/app.css. Run `npm run build:css` after changing templates. */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./*/templates/**/*.html",
    "./static/js/app.js",
    "./static/js/chart.js",
    "./core/forms.py",
    "./core/templatetags/*.py",
    "./core/charts.py",
  ],
  // Status classes are built from model values in templates (e.g. rag-bar-{{ rag }}).
  safelist: [
    { pattern: /^(rag|rag-bar|dot|st|s)-(green|yellow|red|done|none|on_track|off_track|future)$/ },
  ],
  theme: {
    extend: {
      colors: {
        brand: "#000000",
        ink: "#0a0a0a",
        bolt: { DEFAULT: "#D5FF03", 50: "#fbffe6", 100: "#f4ffc2", 200: "#ebff85", 300: "#e0ff47", 400: "#D5FF03", 600: "#a8cc00", 700: "#7d9900" },
        paper: "#f6f6f4",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Montserrat", "Inter", "ui-sans-serif", "sans-serif"],
      },
      boxShadow: {
        soft: "0 1px 2px rgb(0 0 0 / .04), 0 1px 1px rgb(0 0 0 / .02)",
        lift: "0 10px 30px -12px rgb(0 0 0 / .25), 0 2px 6px rgb(0 0 0 / .06)",
        panel: "-20px 0 60px -20px rgb(0 0 0 / .35)",
      },
      borderRadius: { xl2: "1.125rem" },
    },
  },
};
