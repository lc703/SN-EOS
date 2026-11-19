/** Compiles static/css/app.css. Run scripts/build_css.sh after changing templates or class names in Python/JS. */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./*/templates/**/*.html",
    "./*/views.py",
    "./*/forms.py",
    "./core/forms.py",
    "./core/charts.py",
    "./core/templatetags/*.py",
    "./static/js/app.js",
    "./static/js/chart.js",
  ],
  theme: {
    extend: {
      colors: { brand: "#000000", bolt: "#D5FF03", paper: "#f6f6f4" },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Montserrat", "Inter", "ui-sans-serif", "sans-serif"],
      },
    },
  },
};
