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

describe("ProjectDetailView phase 2F", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/projects/1");
    vi.resetAllMocks();
    vi.mocked(api.getProject).mockResolvedValue(project([shot(1, "Shot 1")]));
    vi.mocked(api.listProviders).mockResolvedValue([]);
    vi.mocked(api.getWorkerStatus).mockResolvedValue({
      stale_after_seconds: 45,
      generation: { worker_type: "GENERATION", online_count: 0, total_count: 0, stale_after_seconds: 45, workers: [] },
      result: { worker_type: "RESULT", online_count: 0, total_count: 0, stale_after_seconds: 45, workers: [] },
    });
  });

  it("shows provider settings and worker offline hints", async () => {
    vi.mocked(api.listProviders).mockResolvedValue([
      {
        provider_id: "fake-http",
        display_name: "Fake HTTP",
        configured: true,
        configuration_error: null,
        defaults: { image_model: "img", video_model: "vid", aspect_ratio: "16:9", duration_seconds: 4 },
        capabilities: {
          provider_id: "fake-http",
          display_name: "Fake HTTP",
          text_to_image: true,
          image_to_image: false,
          image_to_video: true,
          first_last_frame_video: true,
          video_extension: false,
          supports_seed: true,
          supports_cancel: true,
          supports_negative_prompt: true,
          max_reference_images: 2,
          max_duration_seconds: 12,
          supported_aspect_ratios: ["16:9"],
          supported_output_types: ["png", "mp4"],
        },
      },
    ]);

    const wrapper = await mountView();

    expect(wrapper.text()).toContain("Generation Settings");
    expect(wrapper.text()).toContain("Workers");
    expect(wrapper.text()).toContain("Start: python -m app.workers.cli generation");
  });

  it("groups task attempts by request and shows actual generation mode", async () => {
    const current = project([shot(1, "Shot 1")]);
    current.requests = [
      {
        id: 10,
        project_id: 1,
        shot_id: 1,
        kind: "KEYFRAME",
        provider_name: "fake-http",
        effective_provider_id: "fake-http",
        model: "img",
        generation_mode: "TEXT_TO_IMAGE",
        aspect_ratio: "16:9",
        seed: 7,
        duration_seconds: null,
        allow_capability_fallback: false,
        status: "RUNNING",
        error_code: null,
        error_message: null,
        created_at: "",
        updated_at: "",
      },
    ];
    current.tasks = [
      phase2fTask({
        id: 99,
        generation_request_id: 10,
        remote_job_id: "remote-job-abcdef123456",
        remote_status: "running",
        remote_progress: 0.5,
      }),
    ];
    vi.mocked(api.getProject).mockResolvedValue(current);

    const wrapper = await mountView();

    expect(wrapper.text()).toContain("Request #10 KEYFRAME");
    expect(wrapper.text()).toContain("mode TEXT_TO_IMAGE");
    expect(wrapper.text()).toContain("job remote...3456");
    expect(wrapper.text()).toContain("progress 50%");
  });

  it("uses backend shot actions to disable unavailable generation commands", async () => {
    const blocked = shot(1, "Blocked");
    blocked.actions = { can_generate_keyframe: false, can_generate_video: false, reasons: ["LOCKED"] };
    vi.mocked(api.getProject).mockResolvedValue(project([blocked]));

    const wrapper = await mountView();

    const disabledButtons = wrapper.findAll("button").filter((button) => button.attributes("disabled") !== undefined);
    expect(disabledButtons.length).toBeGreaterThan(0);
  });
});

function phase2fTask(patch: Partial<ProjectDetail["tasks"][number]>): ProjectDetail["tasks"][number] {
  return {
    id: 1,
    generation_request_id: 1,
    project_id: 1,
    shot_id: 1,
    task_type: "KEYFRAME_GENERATION",
    provider_id: "mock",
    status: "RUNNING",
    remote_job_id: null,
    remote_status: null,
    remote_progress: null,
    processing_stage: null,
    processing_progress: null,
    attempt_number: 1,
    retry_count: 0,
    max_attempts: 3,
    can_cancel: true,
    can_retry: false,
    retry_of_task_id: null,
    root_task_id: 1,
    result_count: 0,
    result_hosts: [],
    processing_status: null,
    next_retry_at: null,
    last_polled_at: null,
    next_poll_at: null,
    submission_deadline_at: null,
    job_deadline_at: null,
    cancellation_deadline_at: null,
    cancel_requested_at: null,
    cancelled_at: null,
    cancel_reason: null,
    last_retry_delay_seconds: null,
    result_retry_count: 0,
    max_result_attempts: 3,
    next_result_retry_at: null,
    last_result_retry_delay_seconds: null,
    locked_by: null,
    locked_until: null,
    error_code: null,
    error_message: null,
    result_asset_id: null,
    created_at: "",
    updated_at: "",
    started_at: null,
    completed_at: null,
    ...patch,
  };
}

vi.mock("@/api/client", () => ({
  api: {
    getProject: vi.fn(),
    listProviders: vi.fn(),
    getWorkerStatus: vi.fn(),
    updateProject: vi.fn(),
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
    image_provider_id: null,
    video_provider_id: null,
    image_model: null,
    video_model: null,
    default_aspect_ratio: "16:9",
    default_video_duration_seconds: null,
    default_seed: null,
    created_at: "",
    updated_at: "",
    assets: [],
    requests: [],
    tasks: [],
    logs: [
      {
        id: 1,
        request_id: 9,
        task_id: null,
        shot_id: shots[0]?.id ?? null,
        level: "INFO",
        message: "created",
        created_at: "",
      },
    ],
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
    actions: {
      can_generate_keyframe: true,
      can_generate_video: false,
      reasons: ["VIDEO_REQUIRES_KEYFRAME_APPROVED"],
    },
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
  ElSelect: { template: "<select><slot /></select>" },
  ElOption: { template: "<option><slot /></option>" },
  ElSwitch: { template: "<input type=\"checkbox\" />" },
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
  vi.mocked(api.listProviders).mockResolvedValue([]);
  vi.mocked(api.getWorkerStatus).mockResolvedValue({
    stale_after_seconds: 45,
    generation: { worker_type: "GENERATION", online_count: 0, total_count: 0, stale_after_seconds: 45, workers: [] },
    result: { worker_type: "RESULT", online_count: 0, total_count: 0, stale_after_seconds: 45, workers: [] },
  });
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
    vi.mocked(api.listProviders).mockResolvedValue([]);
    vi.mocked(api.getWorkerStatus).mockResolvedValue({
      stale_after_seconds: 45,
      generation: { worker_type: "GENERATION", online_count: 0, total_count: 0, stale_after_seconds: 45, workers: [] },
      result: { worker_type: "RESULT", online_count: 0, total_count: 0, stale_after_seconds: 45, workers: [] },
    });
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
