import { create } from "zustand";
import type { ControlProject } from "@/api/controlPlane";

type ProjectState = {
  projects: ControlProject[];
  currentProjectId: string | null;
  setProjects: (projects: ControlProject[]) => void;
  setCurrentProjectId: (projectId: string | null) => void;
};

export const useProjectStore = create<ProjectState>((set) => ({
  projects: [],
  currentProjectId: localStorage.getItem("vl_current_project"),
  setProjects: (projects) => set((state) => ({
    projects,
    currentProjectId: state.currentProjectId && projects.some((project) => project.id === state.currentProjectId)
      ? state.currentProjectId
      : null,
  })),
  setCurrentProjectId: (currentProjectId) => {
    if (currentProjectId) localStorage.setItem("vl_current_project", currentProjectId);
    else localStorage.removeItem("vl_current_project");
    set({ currentProjectId });
  },
}));
