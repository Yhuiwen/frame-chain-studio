import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { VisualExperimentPlanOnly, VisualRegenerationPlanOnly } from "@/api/client";
import VisualRegenerationView from "@/views/VisualRegenerationView.vue";

vi.mock("vue-router", () => ({ useRoute: () => ({ params: { projectId: "22" } }) }));

function plan(strategy: string, cost: string, status: "BLOCKED" | "READY_FOR_REVIEW"): VisualRegenerationPlanOnly {
  return { strategy, status, scope: "FROM_SHOT_TO_END", regenerationPlanHash: strategy.repeat(64).slice(0,64), promptContractHash: "c".repeat(64), targetShotIds: [62,63], reusedAssets: strategy.includes("MINIMUM") ? [91] : [], reasonCodes: ["CHARACTER_STYLE_DRIFT","INTRA_SHOT_SCENE_CUT"], blockedReasons: status === "BLOCKED" ? ["SHOT2_KEYFRAME_REUSE_REQUIRES_DELTA_REVIEW"] : [], promptContract: { character: { identity_description: "red toy robot" }, camera: { camera_motion_policy: "FIXED" }, environment: { background: "gray studio" }, style: { rendering_style: "3D toy photography" }, motion: { allowed_motion: "small gesture" } }, compiledImagePrompt: { prompt: "CHARACTER LOCK", negativeConstraints: "no cuts", promptHash: "i".repeat(64) }, compiledVideoPrompt: { prompt: "CAMERA LOCK\nMOTION DELTA", negativeConstraints: "No scene cuts", promptHash: "v".repeat(64) }, keyframeDeltaStatus: status === "BLOCKED" ? "INCONCLUSIVE" : "PRE_GENERATION_ESTIMATE", splitSuggestion: { splitRecommended: false }, imageRequests: strategy.includes("MINIMUM") ? 1 : 2, videoRequests: 2, totalVideoSeconds: "8.0", estimatedBillingUnits: cost, maximumBillingUnits: "190", billingUnit: "TOAPIS_CREDIT", pricingReviewed: true, pricingFresh: true, crossShotSeamStatus: "PASSED", readyForHumanReview: status === "READY_FOR_REVIEW", readyForPaidExecution: false, recommendationReason: "minimum deterministic repair" };
}

function experiment(candidateType: string): VisualExperimentPlanOnly {
  const short = candidateType === "SHORT_CONTINUITY_CANARY";
  return { candidateType, experimentPlanHash:(short?"s":"f").repeat(64),selectedRegenerationPlanHash:"r".repeat(64),selectedBaselineAssetId:null,baselineHash:null,
    baselineCandidates:[{assetId:82,automaticScore:0,styleAssessment:"REJECTED_STYLE",exclusionReasons:["FLAT_CARTOON_ANCHOR"]},{assetId:83,automaticScore:92,styleAssessment:"THREE_DIMENSIONAL_TOY_CANDIDATE",exclusionReasons:[]}],
    baselineHumanReviewStatus:"PENDING",planHumanReviewStatus:"PENDING",authorizationStatus:"BLOCKED",recommendedCandidate:"SHORT_CONTINUITY_CANARY",promptContractHash:"p".repeat(64),compiledImagePromptHashes:["i".repeat(64)],compiledVideoPromptHashes:["v".repeat(64)],
    promptContracts:{shot1:{motion:{allowed_motion:"small head turn"}},shot2:{motion:{allowed_motion:"small arm motion"}}},compiledPrompts:[{image:{prompt:"LOCKED IMAGE",promptHash:"i".repeat(64)},video:{prompt:"LOCKED VIDEO MOTION",promptHash:"v".repeat(64)}}],
    imageRequests:2,videoRequests:2,videoDurationSecondsEach:short?2:4,totalVideoSeconds:short?4:8,estimatedBillingUnits:short?"92.6":"172.6",maximumBillingUnits:short?"110":"190",billingUnit:"TOAPIS_CREDIT",readyForExplicitAuthorization:false,readyForPaidExecution:false };
}

describe("VisualRegenerationView", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body)) as { strategy?: string; candidate?: string };
    const payload = url.includes("visual-experiments") ? experiment(body.candidate!) : body.strategy === "MINIMUM_COST_REPAIR" ? plan(body.strategy,"166.3","BLOCKED") : plan(body.strategy!,"172.6","READY_FOR_REVIEW");
    return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
  })));
  afterEach(() => vi.restoreAllMocks());
  it("shows two candidates, failures, seam success and no execution", async () => {
    const wrapper = mount(VisualRegenerationView); await flushPromises();
    expect(wrapper.text()).toContain("MINIMUM_COST_REPAIR"); expect(wrapper.text()).toContain("HIGHER_CONTINUITY_REPAIR");
    expect(wrapper.text()).toContain("CHARACTER_STYLE_DRIFT"); expect(wrapper.text()).toContain("跨 Shot 衔接已经通过");
    expect(wrapper.text()).toContain("READY_FOR_PAID_EXECUTION=false"); expect(wrapper.text()).toContain("172.6");
    expect(wrapper.html()).not.toContain("D:\\AIProjects"); expect(wrapper.html()).not.toContain(["files","toapis","com"].join("."));
  });
  it("shows baseline exclusions and two non-executing experiment candidates", async () => {
    const wrapper=mount(VisualRegenerationView); await flushPromises();
    expect(wrapper.text()).toContain("Asset 82"); expect(wrapper.text()).toContain("REJECTED_STYLE");
    expect(wrapper.text()).toContain("SHORT_CONTINUITY_CANARY"); expect(wrapper.text()).toContain("FULL_CONTINUITY_RETEST");
    expect(wrapper.text()).toContain("92.6"); expect(wrapper.text()).toContain("PLAN_REVIEWED ≠ PAID_AUTHORIZED");
    expect(wrapper.text()).toContain("readyForPaidExecution=false");
  });
  it("shows inherited locks, prompt preview, delta and plan hash", async () => {
    const wrapper = mount(VisualRegenerationView); await flushPromises();
    expect(wrapper.text()).toContain("继承自 Shot 1"); expect(wrapper.text()).toContain("Prompt 编译预览");
    expect(wrapper.text()).toContain("PRE_GENERATION_ESTIMATE"); expect(wrapper.text()).toContain("Plan Hash");
    expect(wrapper.text()).toContain("批准方案内容（不等于付费授权）");
  });
});
