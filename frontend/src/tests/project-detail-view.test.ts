import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, type ProjectDetail } from "@/api/client";
import ProjectDetailView from "@/views/ProjectDetailView.vue";

const mocks = vi.hoisted(() => ({
  confirm: vi.fn(),
  error: vi.fn(),
}));

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: { id: "1" } }),
}));

vi.mock("element-plus", async () => {
  const actual = await vi.importActual<typeof import("element-plus")>("element-plus");
  return {
    ...actual,
    ElMessage: { error: mocks.error, success: vi.fn(), warning: vi.fn() },
    ElMessageBox: { confirm: mocks.confirm },
  };
});

vi.mock("@/api/client", () => ({
  api: {
    getProject: vi.fn(),
    deleteShot: vi.fn(),
    generateKeyframe: vi.fn(),
    approveKeyframe: vi.fn(),
    rejectKeyframe: vi.fn(),
    generateVideo: vi.fn(),
    approveVideo: vi.fn(),
    rejectVideo: vi.fn(),
  },
}));

function project(shots: ProjectDetail["shots"]): ProjectDetail {
  return {
    id: 1,
    name: "Demo",
    description: "",
    created_at: "",
    updated_at: "",
    assets: [],
    requests: [],
    logs: [{ id: 1, request_id: 9, shot_id: shots[0]?.id ?? null, level: "INFO", message: "created", created_at: "" }],
    shots,
  };
}

function shot(id: number, title: string): ProjectDetail["shots"][number] {
  return {
    id,
    project_id: 1,
    sort_order: id - 1,
    title,
    description: "",
    duration_seconds: 4,
    prompt: "",
    negative_prompt: "",
    status: "DRAFT",
    start_frame_asset_id: null,
    start_frame: id === 2 ? {
      asset_id: 5,
      url: "/api/media/5",
      source_type: "inherited",
      source_shot_id: 1,
      source_shot_title: "Shot 1",
      file_name: "tail-frame.png",
      created_at: "now",
    } : null,
    target_keyframe: null,
    locked_tail_frame: null,
  };
}

const stubs = {
  ElButton: {
    props: ["nativeType", "loading", "disabled"],
    emits: ["click"],
    inheritAttrs: false,
    template: "<button :class=\"$attrs.class\" :type=\"nativeType || 'button'\" :disabled=\"disabled || loading\" @click=\"$emit('click', $event)\"><slot /></button>",
  },
  ElTag: { template: "<span><slot /></span>" },
  ElForm: { template: "<form @submit=\"$emit('submit', $event)\"><slot /></form>" },
  ElFormItem: { template: "<label><slot /></label>" },
  ElInput: { template: "<input />" },
  ElInputNumber: { template: "<input />" },
  ElImage: { props: ["src"], template: "<img :src=\"src\" />" },
  ElEmpty: { props: ["description"], template: "<div>{{ description }}</div>" },
  ElTimeline: { template: "<div><slot /></div>" },
  ElTimelineItem: { template: "<div><slot /></div>" },
};

async function mountView() {
  setActivePinia(createPinia());
  if (!vi.mocked(api.getProject).getMockImplementation()) {
    vi.mocked(api.getProject).mockResolvedValue(project([shot(1, "Shot 1"), shot(2, "Shot 2")]));
  }
  const wrapper = mount(ProjectDetailView, {
    global: {
      stubs,
      directives: { loading: vi.fn() },
    },
  });
  await flushPromises();
  return wrapper;
}

describe("ProjectDetailView", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/projects/1");
    vi.resetAllMocks();
    vi.mocked(api.getProject).mockResolvedValue(project([shot(1, "Shot 1"), shot(2, "Shot 2")]));
  });

  it("renders delete buttons and skips API when confirmation is cancelled", async () => {
    mocks.confirm.mockRejectedValueOnce(new Error("cancel"));
    const wrapper = await mountView();

    expect(wrapper.text()).toContain("删除 Shot");
    await wrapper.find(".delete-shot").trigger("click");
    await flushPromises();

    expect(api.deleteShot).not.toHaveBeenCalled();
  });

  it("calls delete API after confirmation and refreshes the list without page reload", async () => {
    const beforeHref = window.location.href;
    mocks.confirm.mockResolvedValueOnce(undefined);
    vi.mocked(api.deleteShot).mockResolvedValue(undefined);
    vi.mocked(api.getProject)
      .mockResolvedValueOnce(project([shot(1, "Shot 1"), shot(2, "Shot 2")]))
      .mockResolvedValueOnce(project([shot(2, "Shot 2")]));
    const wrapper = await mountView();

    await wrapper.find(".delete-shot").trigger("click");
    await flushPromises();

    expect(api.deleteShot).toHaveBeenCalledWith(1);
    const timelineText = wrapper.find(".timeline").text();
    expect(timelineText).not.toContain("Shot 1");
    expect(timelineText).toContain("Shot 2");
    expect(window.location.href).toBe(beforeHref);
  });

  it("shows backend error when delete fails", async () => {
    mocks.confirm.mockResolvedValueOnce(undefined);
    vi.mocked(api.deleteShot).mockRejectedValueOnce(new Error("backend says no"));
    const wrapper = await mountView();

    await wrapper.find(".delete-shot").trigger("click");
    await flushPromises();

    expect(mocks.error).toHaveBeenCalledWith("backend says no");
  });

  it("expands log details without submitting forms or changing route", async () => {
    const wrapper = await mountView();
    const submit = vi.fn();
    wrapper.find("form").element.addEventListener("submit", submit);

    await wrapper.find(".log-row").trigger("click");

    expect(wrapper.text()).toContain("request: 9");
    expect(submit).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe("/projects/1");
  });

  it("displays inherited start frame thumbnail and source information", async () => {
    const wrapper = await mountView();
    await wrapper.findAll(".timeline-item")[1].trigger("click");

    expect(wrapper.find('img[src="/api/media/5"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("继承自 Shot 1");
  });
});
