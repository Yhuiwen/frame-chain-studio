import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/api/client";
import { useStudioStore } from "@/stores/studio";

vi.mock("@/api/client", () => ({
  api: {
    listProjects: vi.fn(),
    createProject: vi.fn(),
    getProject: vi.fn(),
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
});
