import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, type ProjectDetail, type VisualContinuityReport, type VisualPreviewManifest } from "@/api/client";
import FrameComparison from "@/components/FrameComparison.vue";
import VisualContinuityReview from "@/views/VisualContinuityReview.vue";

vi.mock("vue-router", () => ({ useRoute: () => ({ params: { projectId: "22" }, query: {} }) }));

const report: VisualContinuityReport = {
  id: 2, project_id: 22, shot_id: 63, video_asset_id: 92, start_anchor_asset_id: 90,
  target_keyframe_asset_id: 91, tail_frame_asset_id: 93, analysis_version: "visual-continuity-v1",
  config_hash: "a".repeat(64), report_hash: "b".repeat(64), technical_status: "PASSED",
  automatic_visual_status: "FAILED", human_visual_status: "REJECTED", overall_visual_status: "FAILED",
  scene_cut_status: "FAILED", anchor_match_status: "PASSED", target_match_status: "PASSED",
  camera_stability_status: "INCONCLUSIVE", composition_drift_status: "FAILED",
  subject_scale_drift_status: "FAILED", style_drift_status: "INCONCLUSIVE",
  cross_shot_seam_status: "PASSED", production_gate_status: "BLOCKED",
  metrics: { video: { duration: 4.04, fps: 24 }, sceneCutCandidates: [{ seconds: 2.041667, decision: "UNEXPECTED_HARD_CUT" }], config: { scene_cut_confirmed_threshold: "0.30" } },
  rejection_reasons: ["CHARACTER_STYLE_DRIFT", "INTRA_SHOT_SCENE_CUT", "COMPOSITION_DISCONTINUITY", "SUBJECT_SCALE_DRIFT"],
  created_at: "2026-07-21T00:00:00", updated_at: "2026-07-21T00:00:00",
};
const manifest: VisualPreviewManifest = {
  reportId: 2, projectId: 22, shotId: 63, videoAssetId: 92, analysisVersion: report.analysis_version,
  configHash: report.config_hash, reportHash: report.report_hash, sceneCutCandidates: [], promptContract: null,
  promptContractWarning: "No structured prompt contract was persisted for this historical report.",
  crossShotSeam: { status: "PASSED", lineageVerified: true, remoteLastFrameUsed: false },
  comparisonPairs: [{ kind: "SCENE_CUT_CANDIDATE", leftSource: "VIDEO_FRAME", rightSource: "VIDEO_FRAME", leftAssetId: 92, rightAssetId: 92, leftTimestamp: 2, rightTimestamp: 2.083, metrics: { ssim: 0.2 }, status: "UNEXPECTED_HARD_CUT", reasonCodes: ["INTRA_SHOT_SCENE_CUT"] }],
};
const project = { id: 22, name: "Run 6", description: "", assets: [{ id: 94, project_id: 22, shot_id: null, type: "PROJECT_RENDER", url: "/api/media/94", file_name: "render.mp4", mime_type: "video/mp4", source_asset_id: null, sha256: null, file_size: null, width: 1280, height: 720, duration_seconds: 8.08, fps: 24 }], shots: [], requests: [], tasks: [], renders: [], completion: {}, quality_checks: [], logs: [], created_at: "", updated_at: "", image_provider_id: null, video_provider_id: null, image_model: null, video_model: null, default_aspect_ratio: null, default_video_duration_seconds: null, default_seed: null } as unknown as ProjectDetail;

describe("VisualContinuityReview", () => {
  beforeEach(() => {
    vi.spyOn(api, "listVisualReports").mockResolvedValue([report]);
    vi.spyOn(api, "getProject").mockResolvedValue(project);
    vi.spyOn(api, "getVisualManifest").mockResolvedValue(manifest);
    vi.spyOn(api, "getVisualReviewHistory").mockResolvedValue([]);
  });
  it("separates technical, automatic, human and production states", async () => {
    const wrapper = mount(VisualContinuityReview, { global: { stubs: { ElDescriptions: false, ElDescriptionsItem: false, ProviderRunVisualReview: true } } });
    await flushPromises();
    expect(wrapper.text()).toContain("技术验证"); expect(wrapper.text()).toContain("自动视觉");
    expect(wrapper.text()).toContain("未通过"); expect(wrapper.text()).toContain("已阻断");
    expect(wrapper.text()).toContain("供应商任务成功和视频可播放，不代表生产视觉质量通过");
    expect(wrapper.text()).toContain("启发式指标，不等同于语义主体识别");
    expect(wrapper.text()).toContain("零费用");
    expect(wrapper.html()).not.toContain("D:\\AIProjects");
    expect(wrapper.html()).not.toContain(["files", "toapis", "com"].join("."));
    expect(wrapper.find("button.timeline-marker.confirmed").exists()).toBe(true);
  });
  it("keeps historical Run 6 rejection locked", async () => {
    const wrapper = mount(VisualContinuityReview, { global: { stubs: { ProviderRunVisualReview: true } } }); await flushPromises();
    const submit = wrapper.findAll("el-button").find((item) => item.text().includes("提交人工审核"));
    expect(submit?.attributes("disabled")).toBe("true");
    expect(wrapper.html()).toContain("历史未通过结论已锁定展示");
  });
});

describe("FrameComparison", () => {
  it("switches comparison modes and labels both safe sources", async () => {
    const wrapper = mount(FrameComparison, { props: { leftUrl: "/api/media/87", rightUrl: "/api/media/90", leftLabel: "Tail Asset 87", rightLabel: "Start Asset 90" } });
    expect(wrapper.text()).toContain("并排"); expect(wrapper.text()).toContain("差异图");
    expect(wrapper.text()).toContain("Tail Asset 87"); expect(wrapper.text()).toContain("Start Asset 90");
  });
});
