import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/api/client";
import { ACTIVE_TASK_STATUSES, useStudioStore } from "@/stores/studio";

vi.mock("@/api/client", () => ({
  api: {
    listProjects: vi.fn(),
    createProject: vi.fn(),
    getProject: vi.fn(),
    deleteShot: vi.fn(),
  },
}));

describe("studio store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("loads projects", async () => {
    vi.mocked(api.listProjects).mockResolvedValue([
      { id: 1, name: "Demo", description: "", created_at: "", updated_at: "" },
    ]);
    const store = useStudioStore();
    await store.loadProjects();
    expect(store.projects).toHaveLength(1);
    expect(store.projects[0].name).toBe("Demo");
  });

  it("deletes a shot and preserves the current route-free refresh flow", async () => {
    vi.mocked(api.getProject).mockResolvedValue({
      id: 1,
      name: "Demo",
      description: "",
      created_at: "",
      updated_at: "",
      assets: [],
      requests: [],
      tasks: [],
      logs: [],
      shots: [
        {
          id: 2,
          project_id: 1,
          sort_order: 0,
          title: "Shot 2",
          description: "",
          duration_seconds: 4,
          prompt: "",
          negative_prompt: "",
          status: "DRAFT",
          start_frame_asset_id: null,
          start_frame: null,
          target_keyframe: null,
          locked_tail_frame: null,
        },
      ],
    });
    vi.mocked(api.deleteShot).mockResolvedValue(undefined);
    const store = useStudioStore();
    store.current = {
      id: 1,
      name: "Demo",
      description: "",
      created_at: "",
      updated_at: "",
      assets: [],
      requests: [],
      tasks: [],
      logs: [],
      shots: [],
    };

    await store.deleteShot(1);

    expect(api.deleteShot).toHaveBeenCalledWith(1);
    expect(store.current?.shots).toHaveLength(1);
  });

  it("treats result processing states as active", () => {
    expect(ACTIVE_TASK_STATUSES.has("RESULT_READY")).toBe(true);
    expect(ACTIVE_TASK_STATUSES.has("PROCESSING_RESULT")).toBe(true);
    expect(ACTIVE_TASK_STATUSES.has("SUCCEEDED")).toBe(false);
  });
});
