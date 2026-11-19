# Tamala Leika website

The website of [Tamala Leika](https://www.youtube.com/@tamalaleika), hand-drawn finance explainers:
one page per short, with the video and an article.

This repo is generated. The source lives in a private repo and is pushed here by
`python3 site/build.py deploy`; changes made here are overwritten. GitHub Actions builds the pages
from `content/videos.json` and `pages/` (`python3 build.py build`, standard library only) on every
push and just after each release slot, so a short gets its page once it is public on YouTube.
