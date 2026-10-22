import { ArrowUpRight, Film } from "lucide-react";
import { LandingHero } from "@/components/landing/landing-hero";
import { ProjectLauncher } from "@/components/landing/project-launcher";
import styles from "@/components/landing/landing.module.css";

export default function Home() {
  return <main className={styles.landing} data-landing-page>
    <a className="skipLink" href="#workspace">Skip to projects</a>
    <header className={styles.header}>
      <a className={styles.brand} href="#" aria-label="CineDub home"><span><Film size={18} /></span>CineDub</a>
      <nav aria-label="Main navigation"><a className={styles.previewLink} href="#studio-preview">The workspace</a><a className={styles.headerCta} href="#workspace">Open studio <ArrowUpRight size={14} /></a></nav>
    </header>
    <LandingHero />
    <ProjectLauncher />
    <footer className={styles.footer}><span>CineDub <span>— A workspace for stories in another language.</span></span><span>ENGLISH <span>→</span> മലയാളം</span></footer>
  </main>;
}
