import { useQuery } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { ApiError, api, unwrap, type Me, type Project } from "./api";

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => unwrap(api.GET("/v1/health")),
    staleTime: Infinity,
  });
}

export function useMe() {
  return useQuery<Me, ApiError>({
    queryKey: ["me"],
    queryFn: () => unwrap(api.GET("/v1/me")),
    retry: false,
  });
}

interface ProjectState {
  project: Project | null;
  setProjectId: (id: string) => void;
}

const ProjectContext = createContext<ProjectState>({
  project: null,
  setProjectId: () => undefined,
});
const PROJECT_KEY = "sv.project";

export function ProjectProvider({
  projects,
  children,
}: {
  projects: Project[];
  children: ReactNode;
}) {
  const [projectId, setProjectId] = useState<string | null>(() => {
    try {
      return localStorage.getItem(PROJECT_KEY);
    } catch {
      return null;
    }
  });
  const project = projects.find((p) => p.project_id === projectId) ?? projects[0] ?? null;
  useEffect(() => {
    try {
      if (project) localStorage.setItem(PROJECT_KEY, project.project_id);
    } catch {
      /* not remembered */
    }
  }, [project]);
  return (
    <ProjectContext.Provider value={{ project, setProjectId }}>{children}</ProjectContext.Provider>
  );
}

export function useProject() {
  return useContext(ProjectContext);
}

export function hasRole(project: Project | null, ...roles: Project["roles"]): boolean {
  return !!project && project.roles.some((role) => roles.includes(role));
}
