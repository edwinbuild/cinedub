"use client";

import { AudioLines, Clapperboard, FolderOpen, Settings2, SlidersHorizontal, Workflow } from "lucide-react";
import { TooltipButton } from "@/components/tooltip-button";

export const WORKSPACE_TOOLS = [
  { id: "media", label: "Media", icon: FolderOpen, description: "Import and prepare your scene" },
  { id: "workflow", label: "Workflow", icon: Workflow, description: "Transcribe, translate and review" },
  { id: "voices", label: "Voices", icon: AudioLines, description: "Cast speakers and choose takes" },
  { id: "analysis", label: "Analysis", icon: SlidersHorizontal, description: "Refine dialogue, timing and delivery" },
  { id: "export", label: "Export", icon: Clapperboard, description: "Mix, review and deliver" },
  { id: "project", label: "Project", icon: Settings2, description: "Revisions, speakers and activity" },
] as const;

export type WorkspaceTool = typeof WORKSPACE_TOOLS[number]["id"];

/** Labelled buttons keep the tools discoverable on both desktop and narrow screens. */
export function ToolNavigation({ active, onChange }: {
  active: WorkspaceTool; onChange: (tool: WorkspaceTool) => void;
}) {
  return <nav className="toolNavigation" aria-label="Workspace tools">
    {WORKSPACE_TOOLS.map(({ id, label, description, icon: Icon }) => <TooltipButton key={id} label={label} description={description}
      aria-pressed={active === id} aria-controls={`tool-${id}`} onClick={() => onChange(id)}>
      <Icon size={20} aria-hidden="true" /><span>{label}</span>
    </TooltipButton>)}
  </nav>;
}
