<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { api, type VisualExperimentPlanOnly, type VisualRegenerationPlanOnly } from "@/api/client";

const route = useRoute();
const projectId = computed(() => Number(route.params.projectId));
const plans = ref<VisualRegenerationPlanOnly[]>([]);
const selected = ref<VisualRegenerationPlanOnly | null>(null);
const loading = ref(true);
const error = ref("");
const experiments = ref<VisualExperimentPlanOnly[]>([]);
const selectedExperiment = ref<VisualExperimentPlanOnly | null>(null);

async function load() {
  loading.value = true;
  try {
    plans.value = await Promise.all(
      ["MINIMUM_COST_REPAIR", "HIGHER_CONTINUITY_REPAIR"].map((strategy) =>
        api.planVisualRegeneration({ project_id: projectId.value, source_run_id: 6, strategy, maximum_billing_units: "190" }),
      ),
    );
    selected.value = plans.value[1];
    experiments.value = await Promise.all(["SHORT_CONTINUITY_CANARY", "FULL_CONTINUITY_RETEST"].map((candidate) =>
      api.planVisualExperiment({project_id:projectId.value,source_run_id:6,candidate}),
    ));
    selectedExperiment.value = experiments.value[0];
  } catch (value) {
    error.value = value instanceof Error ? value.message : "计划加载失败";
  } finally {
    loading.value = false;
  }
}
onMounted(() => void load());
function contractSection(name: string) { return selected.value?.promptContract[name] || {}; }
</script>

<template>
  <main class="regen-page" v-loading="loading">
    <header><div><h1>视觉再生成规划</h1><p>仅生成可审计计划，不上传、不创建 Provider 任务、不产生费用。</p></div><strong>READY_FOR_PAID_EXECUTION=false</strong></header>
    <el-alert v-if="error" :title="error" type="error" />
    <section class="failure panel"><h2>Run 6 源视觉失败摘要</h2><el-tag v-for="reason in plans[0]?.reasonCodes" :key="reason" type="danger">{{ reason }}</el-tag><p>跨 Shot 衔接已经通过；重点修复 Shot 内风格、场景和构图连续性，不重做已通过的技术链路。</p></section>
    <div class="strategies"><button v-for="plan in plans" :key="plan.strategy" :class="{active:selected?.strategy===plan.strategy}" @click="selected=plan"><h2>{{ plan.strategy }}</h2><p>{{ plan.recommendationReason }}</p><b>{{ plan.status }}</b><span>{{ plan.imageRequests }} 图片 / {{ plan.videoRequests }} 视频 / {{ plan.totalVideoSeconds }} 秒</span><span>预计 {{ plan.estimatedBillingUnits }} {{ plan.billingUnit }}</span></button></div>
    <div v-if="selected" class="workspace">
      <section class="panel contract"><h2>Prompt Contract 编辑预览</h2><p>Shot 2 继承 Character、Camera、Environment、Style；MotionDelta 独立。字段仅允许受控文本，保存会生成新 hash。</p><details v-for="name in ['character','camera','environment','style','motion']" :key="name" open><summary>{{ name }} <el-tag v-if="name !== 'motion'">继承自 Shot 1</el-tag><el-tag v-else type="warning">Shot 独立</el-tag></summary><label v-for="(value,key) in contractSection(name)" :key="String(key)">{{ key }}<el-input :model-value="Array.isArray(value) ? value.join(', ') : String(value)" maxlength="500" /></label></details></section>
      <section class="panel"><h2>Prompt 编译预览与字段差异</h2><p>编译顺序固定：Character → Camera → Environment → Style → Motion。</p><h3>图片 Prompt</h3><pre>{{ selected.compiledImagePrompt.prompt }}</pre><h3>视频 Prompt</h3><pre>{{ selected.compiledVideoPrompt.prompt }}</pre><h3>Negative constraints</h3><pre>{{ selected.compiledVideoPrompt.negativeConstraints }}</pre><p>Prompt Hash：{{ selected.compiledVideoPrompt.promptHash }}</p></section>
      <aside><section class="panel"><h2>Keyframe Delta 预检</h2><strong>{{ selected.keyframeDeltaStatus }}</strong><p>候选图尚未生成时仅做 PRE_GENERATION_ESTIMATE，不伪造 SSIM 或 pHash。</p><pre>{{ JSON.stringify(selected.splitSuggestion,null,2) }}</pre></section><section class="panel"><h2>费用估算</h2><p>图片 {{ selected.imageRequests }} 个；视频 {{ selected.videoRequests }} 个；总视频 {{ selected.totalVideoSeconds }} 秒。</p><strong>{{ selected.estimatedBillingUnits }} / 上限 {{ selected.maximumBillingUnits }} {{ selected.billingUnit }}</strong><p>价格已审核：{{ selected.pricingReviewed }} · 新鲜：{{ selected.pricingFresh }}</p><p>actualBillingUnits=null</p></section><section class="panel"><h2>Plan Hash</h2><code>{{ selected.regenerationPlanHash }}</code><p>readyForHumanReview={{ selected.readyForHumanReview }}</p><p>readyForPaidExecution=false</p></section><section class="panel"><h2>人工计划审核</h2><el-checkbox>已查看视觉失败证据</el-checkbox><el-checkbox>理解费用只是估算</el-checkbox><el-checkbox>确认本阶段不执行生成</el-checkbox><el-button disabled>批准方案内容（不等于付费授权）</el-button></section></aside>
    </div>
    <section v-if="selectedExperiment" class="experiment panel">
      <h2>生产视觉基准候选</h2>
      <p>自动分析只能推荐候选，不能批准基准。Baseline 人工审核：<b>{{ selectedExperiment.baselineHumanReviewStatus }}</b></p>
      <div class="baseline-grid"><article v-for="item in selectedExperiment.baselineCandidates" :key="item.assetId" :class="{excluded:item.exclusionReasons.length}"><b>Asset {{ item.assetId }}</b><span>自动评分 {{ item.automaticScore }}</span><span>{{ item.styleAssessment }}</span><small v-if="item.exclusionReasons.length">已排除：{{ item.exclusionReasons.join('、') }}</small></article></div>
      <h2>视觉实验授权候选</h2>
      <p><b>推荐：SHORT_CONTINUITY_CANARY</b>。以较低成本验证新的视觉基准和连续性约束；通过后再考虑 4 秒复验。</p>
      <div class="strategies"><button v-for="item in experiments" :key="item.candidateType" :class="{active:selectedExperiment?.candidateType===item.candidateType}" @click="selectedExperiment=item"><h3>{{ item.candidateType }}</h3><span>2 图片 + 2 视频</span><span>每段 {{ item.videoDurationSecondsEach }} 秒，总计 {{ item.totalVideoSeconds }} 秒</span><strong>{{ item.estimatedBillingUnits }} / 上限 {{ item.maximumBillingUnits }} {{ item.billingUnit }}</strong></button></div>
      <div class="experiment-detail"><article><h3>MotionDelta</h3><pre>{{ JSON.stringify(selectedExperiment.promptContracts,null,2) }}</pre></article><article><h3>编译 Prompt 与 Hash</h3><pre>{{ selectedExperiment.compiledPrompts[0]?.video.prompt }}</pre><code>{{ selectedExperiment.promptContractHash }}</code></article><aside><h3>双重人工审核</h3><p>Baseline：{{ selectedExperiment.baselineHumanReviewStatus }}</p><p>Plan：{{ selectedExperiment.planHumanReviewStatus }}</p><p>PLAN_REVIEWED ≠ PAID_AUTHORIZED</p><p>Authorization：{{ selectedExperiment.authorizationStatus }}</p><h3>Experiment Plan Hash</h3><code>{{ selectedExperiment.experimentPlanHash }}</code><strong>readyForExplicitAuthorization={{ selectedExperiment.readyForExplicitAuthorization }}</strong><strong>readyForPaidExecution=false</strong></aside></div>
    </section>
  </main>
</template>

<style scoped>
.regen-page{padding:24px;background:#f4f6f8;min-height:100vh;color:#182230}.regen-page header{display:flex;justify-content:space-between}.regen-page header strong{color:#b42318}.panel,.strategies button{background:white;border:1px solid #d7dee8;border-radius:10px;padding:14px}.failure{margin:16px 0}.failure .el-tag{margin:4px}.strategies{display:grid;grid-template-columns:1fr 1fr;gap:14px}.strategies button{text-align:left;display:flex;flex-direction:column;gap:7px}.strategies button.active{border:2px solid #2563eb}.workspace{display:grid;grid-template-columns:1.1fr 1fr 320px;gap:14px;margin-top:14px}.contract details{border-top:1px solid #e5e7eb;padding:9px}.contract label{display:block;font-size:12px;margin:8px 0}.panel pre,.panel code{display:block;white-space:pre-wrap;word-break:break-word;background:#f7f8fa;padding:9px;max-height:300px;overflow:auto}aside{display:flex;flex-direction:column;gap:14px}aside .el-checkbox{display:block;margin:8px 0}@media(max-width:1100px){.workspace{grid-template-columns:1fr}.strategies{grid-template-columns:1fr}}
.experiment{margin-top:18px}.baseline-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}.baseline-grid article{display:flex;flex-direction:column;padding:10px;border:1px solid #cbd5e1}.baseline-grid article.excluded{border-color:#dc2626;background:#fff1f2}.experiment-detail{display:grid;grid-template-columns:1fr 1fr 320px;gap:14px;margin-top:14px}.experiment-detail article,.experiment-detail aside{min-width:0}@media(max-width:1100px){.experiment-detail,.baseline-grid{grid-template-columns:1fr}}
</style>
