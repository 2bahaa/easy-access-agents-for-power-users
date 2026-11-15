// Apply the saved theme before first paint (mirrors lib/theme.ts) to avoid a flash.
// A static file (not inline) so the Content-Security-Policy can forbid inline scripts.
try {
  var t = localStorage.getItem("eaa.theme") || "system";
  if (t === "dark" || (t === "system" && matchMedia("(prefers-color-scheme: dark)").matches))
    document.documentElement.classList.add("dark");
} catch (e) {}
