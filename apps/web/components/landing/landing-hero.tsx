"use client";

import { ArrowDown, ArrowUpRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { EditorPreview } from "./editor-preview";
import styles from "./landing.module.css";

export function LandingHero() {
  const root = useRef<HTMLElement>(null);
  const [playing, setPlaying] = useState(true);
  useEffect(() => {
    const element = root.current;
    if (!element) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0;
    function update() {
      frame = 0;
      if (!element) return;
      const progress = reduced.matches ? 0 : Math.max(0, Math.min(1, -element.getBoundingClientRect().top / (window.innerHeight * .7)));
      element.style.setProperty("--landing-scroll", progress.toFixed(4));
    }
    function schedule() { if (!frame) frame = requestAnimationFrame(update); }
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) { (entry.target as HTMLElement).dataset.revealed = "true"; observer.unobserve(entry.target); }
      }
    }, { threshold: .08 });
    const shell = element.closest<HTMLElement>("[data-landing-page]");
    shell?.querySelectorAll<HTMLElement>("[data-reveal]").forEach((target) => observer.observe(target));
    if (shell) shell.dataset.motionReady = "true";
    window.addEventListener("scroll", schedule, { passive: true }); window.addEventListener("resize", schedule);
    reduced.addEventListener("change", schedule); update();
    return () => {
      cancelAnimationFrame(frame); observer.disconnect(); window.removeEventListener("scroll", schedule); window.removeEventListener("resize", schedule);
      reduced.removeEventListener("change", schedule);
    };
  }, []);
  return <section className={styles.heroStage} ref={root} data-paused={!playing} aria-labelledby="landing-title">
    <div className={styles.heroCopy}><div className={styles.headlineBlock}>
      <p className={styles.overline}><i /> THE DUBBING WORKSPACE</p>
      <h1 id="landing-title"><span className={styles.headlineMask}><span>Same story.</span></span><span className={styles.headlineMask}><span className={styles.accentHeadline}>New language.</span></span></h1>
    </div><div className={styles.heroAside}>
      <p>From English to Malayalam.<br />Shape the words. Find the timing.<br />Make every line your own.</p>
      <a className={styles.primaryCta} href="#workspace" onClick={() => requestAnimationFrame(() => document.getElementById("project-name")?.focus({ preventScroll: true }))}>Start a project <ArrowUpRight size={18} /></a>
      <span className={styles.heroNote}>Your scene. Your final say.</span>
    </div></div>
    <div id="studio-preview" className={styles.previewStage}>
      <svg className={styles.motionRibbon} viewBox="0 0 1440 490" fill="none" aria-hidden="true">
        <path className={styles.ribbonBase} d="M-160 390C170 390 130 24 420 46S520 490 900 434 1110-60 1570 110" />
        <path className={styles.ribbonFlow} d="M-160 390C170 390 130 24 420 46S520 490 900 434 1110-60 1570 110" />
        <path className={styles.ribbonFine} d="M-160 420C180 420 145 48 430 68S540 515 910 454 1130-38 1570 132" />
      </svg>
      <div className={styles.previewFrame}><EditorPreview playing={playing} onToggle={() => setPlaying((value) => !value)} /></div>
    </div>
    <div className={styles.heroFootnote}><span><span className={styles.footnoteIndex}>01 —</span> A closer look at your next workspace</span><a href="#workspace">STEP INSIDE <ArrowDown size={13} /></a></div>
  </section>;
}
