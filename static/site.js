// Click to play: the YouTube player (privacy-enhanced domain) loads only when someone presses play,
// so a visit sets no cookies. Analytics (GoatCounter) are cookieless too.
document.querySelectorAll(".short[data-yt]").forEach((box) => {
  const btn = box.querySelector(".short-play");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const f = document.createElement("iframe");
    f.src = `https://www.youtube-nocookie.com/embed/${box.dataset.yt}?autoplay=1&playsinline=1&rel=0&modestbranding=1`;
    f.title = box.dataset.title || "Video";
    f.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
    f.allowFullscreen = true;
    box.replaceChildren(f);
    if (window.goatcounter && window.goatcounter.count) {
      window.goatcounter.count({ path: `play/${box.dataset.yt}`, title: f.title, event: true });
    }
  });
});
