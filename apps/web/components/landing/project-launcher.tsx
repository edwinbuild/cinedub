"use client";

import type { ProjectSummary } from "@cinedub/contracts";
import { ArrowRight, ArrowUpRight, Film, LoaderCircle, Plus, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { TooltipButton } from "@/components/tooltip-button";
import { api } from "@/lib/api";
import styles from "./landing.module.css";

const LANGUAGE_NAMES: Record<string, string> = { "en-IN": "English", "ml-IN": "Malayalam", en: "English", ml: "Malayalam" };

export function ProjectLauncher() {
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try { setError(null); setProjects(await api.projects()); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load projects"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { const timer = window.setTimeout(load, 0); return () => window.clearTimeout(timer); }, [load]);
  async function create(event: FormEvent) {
    event.preventDefault(); if (!name.trim() || saving) return;
    try { setSaving(true); setError(null); const project = await api.createProject(name.trim()); router.push(`/projects/${project.id}`); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not create project"); setSaving(false); }
  }
  return <section id="workspace" className={styles.workspace} data-reveal aria-labelledby="workspace-title">
    <div className={styles.workspaceHeading}><h2 id="workspace-title">Your studio, <span>ready when you are.</span></h2><span>LOCAL WORKSPACE <i /></span></div>
    {error && <div className={styles.launcherError} role="alert">{error}<button type="button" onClick={load}>Refresh projects <RefreshCw size={12} /></button></div>}
    <div className={styles.launcherGrid}>
      <form className={styles.createForm} onSubmit={create}><div className={styles.formHeading}><Plus size={17} /><h3>Start a new project</h3></div>
        <label htmlFor="project-name">Project name</label>
        <div className={styles.createRow}><input id="project-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Give your next scene a name" maxLength={120} required />
          <button className={styles.createButton} type="submit" disabled={saving || !name.trim()}>{saving ? <LoaderCircle size={14} className="spin" /> : null}{saving ? "Creating…" : "Create workspace"}<ArrowUpRight size={16} /></button></div>
        <p>Video or audio · English → Malayalam · up to 2 minutes</p>
      </form>
      <div className={styles.recentProjects}>
        <div className={styles.recentHeading}><h3>Your projects <span>{projects.length.toString().padStart(2, "0")}</span></h3><TooltipButton className={styles.refreshButton} label="Refresh" description="Reload the latest projects saved in this workspace." onClick={load}><RefreshCw size={14} /></TooltipButton></div>
        <div className={styles.projectList}>{loading ? <p className={styles.projectEmpty}><LoaderCircle size={15} className="spin" /> Loading your projects…</p>
          : projects.length ? projects.map((project) => <Link className={styles.projectLink} key={project.id} href={`/projects/${project.id}`}>
            <span className={styles.projectGlyph}><Film size={18} /></span><span><strong>{project.name}</strong><small>{LANGUAGE_NAMES[project.source_language] ?? project.source_language} <ArrowRight size={10} /> {LANGUAGE_NAMES[project.target_language] ?? project.target_language}<i />{project.status.replaceAll("_", " ")}</small></span><ArrowUpRight size={16} />
          </Link>) : <p className={styles.projectEmpty}><Film size={22} /><span>Your next scene starts here.<small>Create a project to open the editor.</small></span></p>}</div>
      </div>
    </div>
  </section>;
}
