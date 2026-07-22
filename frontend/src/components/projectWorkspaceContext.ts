import type { InjectionKey, Ref } from "vue";
import type { ProjectDetail } from "@/api/client";

export interface ProjectWorkspaceContext {
  project: Ref<ProjectDetail | null>;
  projectId: Ref<number>;
  loading: Ref<boolean>;
  refreshProject: () => Promise<void>;
  openMobileNavigation: () => void;
  ready: Ref<Promise<void>>;
}

export const projectWorkspaceKey: InjectionKey<ProjectWorkspaceContext> =
  Symbol("project-workspace");
