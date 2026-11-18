/** Used only when compiling static/css/app.css with the Tailwind v3 standalone CLI (TAILWIND_CDN=0). */
module.exports = {
  content: ["./templates/**/*.html", "./*/templates/**/*.html"],
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
