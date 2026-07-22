import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import { api, type ProviderRunReadiness } from "@/api/client";
import ProviderRunVisualReview from "@/components/ProviderRunVisualReview.vue";

const run: ProviderRunReadiness = {
  id: 6, run_id: 6, provider_profile_id: 1, model_profile_id: null,
  verification_type: "LIVE_CHAIN", status: "PASSED", started_at: null, completed_at: null,
  max_cost: "190", actual_cost: "120", summary: {}, error_code: null, error_message: null,
  created_at: "2026-07-21T00:00:00Z", technical_status: "PASSED", lineage_status: "PASSED",
  automated_visual_status: "FAILED", human_visual_status: "REJECTED", production_status: "BLOCKED",
  production_ready: false, production_blockers: ["HUMAN_VISUAL_REJECTED", "BLOCKING_VISUAL_EVIDENCE"],
  selected_review_asset: { id: 94, type: "PROJECT_RENDER", sha256: "a".repeat(64), created_at: "2026-07-21T00:00:00Z", url: "/api/media/94" },
  current_visual_review: null, legacy_review_evidence: true, legacy_review_report_ids: [1, 2],
  legacy_reason_codes: ["CHARACTER_STYLE_DRIFT"], workflow_approval_only: true,
  scene_cut_check: {
    status: "FAILED", asset_ids: [86, 92], algorithm_version: "scene-cut-v1",
    hard_cut_count: 1, review_candidate_count: 0, missing_asset_ids: [],
    calibration_scope: "SYNTHETIC_FIXTURES_ONLY",
    events: [{ asset_id: 92, timestamp_seconds: "2.083333", previous_timestamp_seconds: "2.000000", pixel_delta: "0.800000", histogram_delta: "0.700000", classification: "HARD_CUT", blocking: true }],
  },
};

const stubs = {
  "el-select": { template: "<div><slot /></div>" }, "el-option": { template: "<span />" },
  "el-alert": { props: ["title"], template: "<div>{{ title }}</div>" }, "el-empty": { template: "<div />" },
  "el-tag": { template: "<span><slot /></span>" }, "el-radio-group": { template: "<div><slot /></div>" },
  "el-radio": { template: "<label><slot /></label>" }, "el-checkbox-group": { template: "<div><slot /></div>" },
  "el-checkbox": { template: "<label><slot /></label>" }, "el-input": { template: "<textarea />" },
  "el-button": { props: ["disabled"], template: "<button :disabled='disabled'><slot /></button>" },
};

describe("ProviderRunVisualReview", () => {
  it("shows technical pass, visual rejection and production block separately", async () => {
    vi.spyOn(api, "listProjectProviderVerificationRuns").mockResolvedValue([run]);
    vi.spyOn(api, "getProviderVisualReviews").mockResolvedValue({ current: null, history: [] });
    const wrapper = mount(ProviderRunVisualReview, { props: { projectId: 22 }, global: { stubs, directives: { loading: () => undefined } } });
    await flushPromises();
    expect(wrapper.text()).toContain("技术验证PASSED");
    expect(wrapper.text()).toContain("人工视觉审核REJECTED");
    expect(wrapper.text()).toContain("生产状态BLOCKED");
    expect(wrapper.text()).toContain("Asset ID94");
    expect(wrapper.text()).toContain("scene-cut-v1");
    expect(wrapper.text()).toContain("2.083333s");
    expect(wrapper.text()).toContain("UNEXPECTED_SCENE_CUT");
    expect(wrapper.text()).toContain("SYNTHETIC_FIXTURES_ONLY");
    expect(wrapper.text()).toContain("技术批准不代表生产批准");
    expect(wrapper.text()).not.toMatch(/live-enable|ExecutePaid/);
  });

  it("blocks a rejected submission without a reason and OTHER without notes", async () => {
    vi.spyOn(api, "listProjectProviderVerificationRuns").mockResolvedValue([{ ...run, legacy_reason_codes: [] }]);
    vi.spyOn(api, "getProviderVisualReviews").mockResolvedValue({ current: null, history: [] });
    const wrapper = mount(ProviderRunVisualReview, { props: { projectId: 22 }, global: { stubs, directives: { loading: () => undefined } } });
    await flushPromises();
    expect(wrapper.text()).toContain("REJECTED 必须选择至少一个原因");
    expect(wrapper.find("button").attributes("disabled")).toBeDefined();
  });

  it("submits the selected Asset and refreshes the Run", async () => {
    vi.spyOn(api, "listProjectProviderVerificationRuns").mockResolvedValue([run]);
    vi.spyOn(api, "getProviderVisualReviews").mockResolvedValue({ current: null, history: [] });
    const create = vi.spyOn(api, "createProviderVisualReview").mockResolvedValue({
      id: 1, project_id: 22, provider_verification_run_id: 6, asset_id: 94,
      asset_sha256: "a".repeat(64), asset_url: "/api/media/94", review_scope: "PROVIDER_VERIFICATION",
      decision: "REJECTED", reason_codes: ["CHARACTER_STYLE_DRIFT"], notes: "checked",
      reviewer_source: "HUMAN_OPERATOR", reviewer_reference: null, reviewed_at: "2026-07-22T00:00:00Z",
      created_at: "2026-07-22T00:00:00Z", idempotency_key: "key",
    });
    vi.spyOn(api, "getProviderVerificationRun").mockResolvedValue(run);
    const wrapper = mount(ProviderRunVisualReview, { props: { projectId: 22 }, global: { stubs, directives: { loading: () => undefined } } });
    await flushPromises();
    (wrapper.vm as unknown as { form: { notes: string } }).form.notes = "checked";
    await wrapper.find("button").trigger("click");
    await flushPromises();
    expect(create).toHaveBeenCalledWith(6, expect.objectContaining({ asset_id: 94, decision: "REJECTED" }), expect.stringContaining("visual-review-6-"));
  });
});
