"use client";

import type { ProjectSummary } from "@cinedub/contracts";
import { ArrowRight, Film, Plus, RefreshCw, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      setProjects(await api.projects());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load projects");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    try {
      setSaving(true);
      const project = await api.createProject(name.trim());
      router.push(`/projects/${project.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create project");
      setSaving(false);
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand"><span className="brandMark"><Film size={19} /></span>CineDub</div>
        <span className="environment"><span /> Local workspace</span>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow"><Sparkles size={14} /> English → Malayalam</p>
          <h1>Shape every line.<br /><span>Keep every intention.</span></h1>
          <p className="heroCopy">A review-first dubbing room where timing, delivery, translation, and voice remain visible and editable.</p>
        </div>
        <form className="createCard" onSubmit={create}>
          <div className="createIcon"><Plus size={21} /></div>
          <div><h2>Start a scene</h2><p>Up to two minutes for the first workflow.</p></div>
          <label htmlFor="project-name">Project name</label>
          <input id="project-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Opening scene" maxLength={120} />
          <button className="primaryButton" disabled={saving || !name.trim()}>{saving ? "Creating…" : "Create workspace"}<ArrowRight size={16} /></button>
        </form>
      </section>

      <section className="projectsSection">
        <div className="sectionHeading"><div><p className="eyebrow">Recent work</p><h2>Your projects</h2></div><button className="iconButton" onClick={load} aria-label="Refresh"><RefreshCw size={16} /></button></div>
        {error && <div className="errorBanner">{error}. Make sure the local API is running on port 8000.</div>}
        {loading ? <div className="emptyState">Loading projects…</div> : projects.length === 0 ? (
          <div className="emptyState"><Film size={28} /><strong>No scenes yet</strong><span>Create the first project above. Nothing from OLD is executed.</span></div>
        ) : (
          <div className="projectGrid">{projects.map((project) => (
            <Link className="projectCard" href={`/projects/${project.id}`} key={project.id}>
              <div className="projectThumb"><Film size={24} /><span>{project.status}</span></div>
              <div className="projectInfo"><h3>{project.name}</h3><p>{project.source_language} <ArrowRight size={12} /> {project.target_language}</p></div>
              <ArrowRight className="projectArrow" size={18} />
            </Link>
          ))}</div>
        )}
      </section>
    </main>
  );
}
