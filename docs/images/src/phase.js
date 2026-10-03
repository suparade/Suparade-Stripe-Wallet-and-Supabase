// Sets <html data-phase> from ?phase=N (see render.sh) so base.css shows the right build-phase content.
document.documentElement.dataset.phase = new URLSearchParams(location.search).get("phase") || "0";
