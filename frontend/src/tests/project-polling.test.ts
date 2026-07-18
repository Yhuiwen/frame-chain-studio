import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { defineComponent } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useProjectPolling } from "@/composables/useProjectPolling";
import { useStudioStore } from "@/stores/studio";

vi.mock("element-plus", async () => {
  const actual = await vi.importActual<typeof import("element-plus")>("element-plus");
  return {
    ...actual,
    ElMessage: { warning: vi.fn(), error: vi.fn(), success: vi.fn() },
  };
});

const Harness = defineComponent({
  setup() {
    return useProjectPolling();
  },
  template: "<button type=\"button\" @click=\"startPolling\">start</button>",
});

describe("useProjectPolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setActivePinia(createPinia());
  });

  it("continues while active tasks exist and stops after terminal state", async () => {
    const store = useStudioStore();
    store.current = {
      id: 1,
      name: "Demo",
      description: "",
      created_at: "",
      updated_at: "",
      shots: [],
      assets: [],
      logs: [],
      requests: [{ id: 1, project_id: 1, shot_id: 1, kind: "KEYFRAME", provider_name: "mock", status: "RUNNING", error_code: null, error_message: null, created_at: "", updated_at: "" }],
    };
    const refresh = vi.spyOn(store, "refreshProjectDetail").mockImplementation(async () => {
      store.current!.requests[0].status = "SUCCEEDED";
    });
    const wrapper = mount(Harness);

    await wrapper.find("button").trigger("click");
    await vi.advanceTimersByTimeAsync(1800);

    expect(refresh).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
    wrapper.unmount();
  });

  it("does not create duplicate timers from repeated starts and clears on unmount", async () => {
    const store = useStudioStore();
    store.current = {
      id: 1,
      name: "Demo",
      description: "",
      created_at: "",
      updated_at: "",
      shots: [],
      assets: [],
      logs: [],
      requests: [{ id: 1, project_id: 1, shot_id: 1, kind: "VIDEO", provider_name: "mock", status: "RUNNING", error_code: null, error_message: null, created_at: "", updated_at: "" }],
    };
    vi.spyOn(store, "refreshProjectDetail").mockResolvedValue(undefined);
    const wrapper = mount(Harness);

    await wrapper.find("button").trigger("click");
    await wrapper.find("button").trigger("click");

    expect(vi.getTimerCount()).toBe(1);
    wrapper.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
