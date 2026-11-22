// Crossfades the background clip to match the chapter in the middle of the screen, and plays
// only that one. With reduced motion, the posters stay up and nothing plays.

(() => {
  const chapters = [...document.querySelectorAll('.chapter')];
  const videos = Object.fromEntries(
    [...document.querySelectorAll('.stage video')].map(v => [v.dataset.shot, v]));
  const dots = [...document.querySelectorAll('.dots a')];
  const end = document.querySelector('.end');
  const still = matchMedia('(prefers-reduced-motion: reduce)');

  let current = null;

  function show(chapter) {
    if (chapter === current) return;
    current = chapter;
    const shot = chapter.dataset.shot;
    for (const c of chapters) c.classList.toggle('on', c === chapter);
    dots.forEach((d, i) => d.classList.toggle('on', chapters[i] === chapter));
    for (const [name, v] of Object.entries(videos)) {
      const on = name === shot;
      v.classList.toggle('on', on);
      if (on) {
        if (v.preload === 'none') v.preload = 'auto';
        if (!still.matches) v.play().catch(() => {});
      } else {
        v.pause();
      }
    }
    preloadNext(chapter);
  }

  // Start loading the next clip while this one is showing, so it is ready on arrival.
  function preloadNext(chapter) {
    const next = chapters[chapters.indexOf(chapter) + 1];
    if (!next) return;
    const v = videos[next.dataset.shot];
    if (v.preload === 'none') { v.preload = 'auto'; v.load(); }
  }

  // A chapter is current once it covers the middle of the screen.
  const io = new IntersectionObserver(entries => {
    for (const e of entries) if (e.isIntersecting) show(e.target);
  }, { rootMargin: '-50% 0px -50% 0px' });
  chapters.forEach(c => io.observe(c));

  // Hide the dots over the closing section, and the scroll hint once scrolling starts.
  new IntersectionObserver(([e]) => {
    document.body.classList.toggle('at-end', e.isIntersecting);
  }, { threshold: .35 }).observe(end);

  addEventListener('scroll', () => {
    document.body.classList.toggle('scrolled', scrollY > 40);
  }, { passive: true });

  // Don't burn CPU in a background tab.
  document.addEventListener('visibilitychange', () => {
    const v = current && videos[current.dataset.shot];
    if (!v) return;
    if (document.hidden) v.pause();
    else if (!still.matches) v.play().catch(() => {});
  });

  still.addEventListener('change', () => {
    const v = current && videos[current.dataset.shot];
    if (!v) return;
    if (still.matches) v.pause(); else v.play().catch(() => {});
  });

  show(chapters[0]);
})();
