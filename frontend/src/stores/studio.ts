import { defineStore } from "pinia";

import {
  api,
  type Asset,
  type GenerationTask,
  type Project,
  type ProjectDetail,
  type ProviderInfo,
  type Shot,
  type TaskLog,
  type WorkersStatus,
} from "@/api/client";

interface StudioState {
  projects: Project[];
  current: ProjectDetail | null;
  selectedShotId: number | null;
  providers: ProviderInfo[];
  workerStatus: WorkersStatus | null;
  loading: boolean;
  refreshing: boolean;
  workersRefreshing: boolean;
}

export const ACTIVE_TASK_STATUSES = new Set([
  "QUEUED",
  "SUBMITTING",
  "GENERATING",
  "PENDING",
  "RUNNING",
  "PROCESSING",
  "RETRY_WAIT",
  "RESULT_READY",
  "PROCESSING_RESULT",
  "CANCELLING",
]);

export const useStudioStore = defineStore("studio", {
  state: (): StudioState => ({
    projects: [],
    current: null,
    selectedShotId: null,
    providers: [],
    workerStatus: null,
    loading: false,
    refreshing: false,
    workersRefreshing: false,
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
    tasksForSelected: (state): GenerationTask[] => {
      const shotId = state.selectedShotId ?? state.current?.shots[0]?.id;
      return (state.current?.tasks ?? []).filter((task) => !shotId || task.shot_id === shotId);
    },
    hasActiveTasks: (state): boolean =>
      (state.current?.requests ?? []).some((request) => ACTIVE_TASK_STATUSES.has(request.status)) ||
      (state.current?.tasks ?? []).some((task) => ACTIVE_TASK_STATUSES.has(task.status)) ||
      (state.current?.renders ?? []).some((render) =>
        ["QUEUED", "PREPARING", "NORMALIZING", "CONCATENATING", "VALIDATING", "FINALIZING"].includes(render.status),
      ),
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
    async loadProject(id: number, options: { showLoading?: boolean } = {}) {
      const showLoading = options.showLoading ?? true;
      const previousSelectedId = this.selectedShotId;
      if (showLoading) this.loading = true;
      try {
        this.current = await api.getProject(id);
        const stillExists = this.current.shots.some((shot) => shot.id === previousSelectedId);
        this.selectedShotId = stillExists ? previousSelectedId : (this.current.shots[0]?.id ?? null);
      } finally {
        if (showLoading) this.loading = false;
      }
    },
    async refreshProjectDetail() {
      if (!this.current) return;
      this.refreshing = true;
      try {
        await this.loadProject(this.current.id, { showLoading: false });
      } finally {
        this.refreshing = false;
      }
    },
    async loadProviders() {
      this.providers = await api.listProviders();
    },
    async refreshWorkers() {
      this.workersRefreshing = true;
      try {
        this.workerStatus = await api.getWorkerStatus();
      } finally {
        this.workersRefreshing = false;
      }
    },
    async updateProjectSettings(patch: Partial<Project>) {
      if (!this.current) return;
      const project = await api.updateProject(this.current.id, patch);
      this.current = { ...this.current, ...project };
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
    async deleteShot(shotId: number) {
      const projectId = this.current?.id;
      if (!projectId) return;
      await api.deleteShot(shotId);
      await this.loadProject(projectId, { showLoading: false });
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
