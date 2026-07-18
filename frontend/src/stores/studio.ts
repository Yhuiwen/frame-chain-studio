import { defineStore } from "pinia";

import { api, type Asset, type Project, type ProjectDetail, type Shot, type TaskLog } from "@/api/client";

interface StudioState {
  projects: Project[];
  current: ProjectDetail | null;
  selectedShotId: number | null;
  loading: boolean;
}

export const useStudioStore = defineStore("studio", {
  state: (): StudioState => ({
    projects: [],
    current: null,
    selectedShotId: null,
    loading: false,
  }),
  getters: {
    selectedShot: (state): Shot | null =>
      state.current?.shots.find((shot) => shot.id === state.selectedShotId) ?? state.current?.shots[0] ?? null,
    assetsByShot:
      (state) =>
      (shotId: number, type?: Asset["type"]): Asset[] =>
        (state.current?.assets ?? []).filter((asset) => asset.shot_id === shotId && (!type || asset.type === type)),
    logsForSelected: (state): TaskLog[] => {
      const shotId = state.selectedShotId ?? state.current?.shots[0]?.id;
      return (state.current?.logs ?? []).filter((log) => !shotId || log.shot_id === shotId);
    },
  },
  actions: {
    async loadProjects() {
      this.loading = true;
      try {
        this.projects = await api.listProjects();
      } finally {
        this.loading = false;
      }
    },
    async createProject(name: string, description: string) {
      const project = await api.createProject({ name, description });
      this.projects.unshift(project);
      return project;
    },
    async loadProject(id: number) {
      this.loading = true;
      try {
        this.current = await api.getProject(id);
        this.selectedShotId = this.current.shots[0]?.id ?? null;
      } finally {
        this.loading = false;
      }
    },
    selectShot(id: number) {
      this.selectedShotId = id;
    },
    async createShot(projectId: number) {
      const shot = await api.createShot(projectId, {
        title: `Shot ${(this.current?.shots.length ?? 0) + 1}`,
        description: "",
        duration_seconds: 4,
        prompt: "",
        negative_prompt: "",
      });
      await this.loadProject(projectId);
      this.selectedShotId = shot.id;
    },
    async updateSelectedShot(patch: Partial<Shot>) {
      if (!this.selectedShot) return;
      await api.updateShot(this.selectedShot.id, patch);
      if (this.current) await this.loadProject(this.current.id);
    },
    async reorder(projectId: number, shots: Shot[]) {
      await api.reorderShots(projectId, shots);
      await this.loadProject(projectId);
    },
    async runAction(action: (shotId: number) => Promise<unknown>) {
      const shot = this.selectedShot;
      const projectId = this.current?.id;
      if (!shot || !projectId) return;
      await action(shot.id);
      await this.loadProject(projectId);
      this.selectedShotId = shot.id;
    },
  },
});
