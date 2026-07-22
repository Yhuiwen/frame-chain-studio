<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";

import { ApiError, api, type ProviderRunReadiness, type ProviderVisualReview } from "@/api/client";
import { formatDateTime, productionBlockerLabel, reviewReasonLabel, statusLabel } from "@/constants/uiText";

const props = defineProps<{ projectId: number }>();
const runs = ref<ProviderRunReadiness[]>([]);
const selected = ref<ProviderRunReadiness | null>(null);
const history = ref<ProviderVisualReview[]>([]);
const busy = ref(false);
const error = ref("");
const form = reactive({ decision: "REJECTED" as "APPROVED" | "REJECTED", reasons: [] as string[], notes: "" });
const reasonCodes = [
  "CHARACTER_STYLE_DRIFT", "CHARACTER_GEOMETRY_DRIFT", "FACE_IDENTITY_DRIFT",
  "MATERIAL_COLOR_DRIFT", "CAMERA_DISCONTINUITY", "COMPOSITION_DISCONTINUITY",
  "SUBJECT_POSITION_DRIFT", "SUBJECT_SCALE_DRIFT", "BACKGROUND_DRIFT", "LIGHTING_DRIFT",
  "UNEXPECTED_SCENE_CUT", "MOTION_ARTIFACT", "DECODE_OR_MEDIA_ISSUE", "OTHER",
];
const cards = computed(() => selected.value ? [
  ["技术验证", selected.value.technical_status],
  ["数据血缘", selected.value.lineage_status],
  ["人工视觉审核", selected.value.human_visual_status],
  ["生产状态", selected.value.production_status],
] : []);
const validationMessage = computed(() => {
  if (form.decision === "REJECTED" && !form.reasons.length) return "选择“未通过”时必须选择至少一个原因。";
  if (form.reasons.includes("OTHER") && !form.notes.trim()) return "选择“其他（OTHER）”时必须填写说明。";
  return "";
});

async function load() {
  busy.value = true;
  error.value = "";
  try {
    runs.value = await api.listProjectProviderVerificationRuns(props.projectId);
    if (runs.value.length) await choose(runs.value[0]);
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "加载验证 Run 失败。";
  } finally {
    busy.value = false;
  }
}

async function choose(run: ProviderRunReadiness) {
  selected.value = run;
  const reviews = await api.getProviderVisualReviews(run.id);
  history.value = reviews.history;
  form.decision = reviews.current?.decision ?? "REJECTED";
  form.reasons = [...(reviews.current?.reason_codes ?? run.legacy_reason_codes ?? [])].filter((value) => reasonCodes.includes(value));
  form.notes = reviews.current?.notes ?? "";
}

async function submit() {
  if (!selected.value?.selected_review_asset || validationMessage.value) return;
  busy.value = true;
  error.value = "";
  try {
    await api.createProviderVisualReview(selected.value.id, {
      asset_id: selected.value.selected_review_asset.id,
      decision: form.decision,
      reason_codes: form.decision === "REJECTED" ? form.reasons : [],
      notes: form.notes,
    }, `visual-review-${selected.value.id}-${Date.now()}`);
    const refreshed = await api.getProviderVerificationRun(selected.value.id);
    runs.value = runs.value.map((run) => run.id === refreshed.id ? refreshed : run);
    await choose(refreshed);
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : "提交审核失败。";
  } finally {
    busy.value = false;
  }
}

watch(() => props.projectId, () => void load());
onMounted(() => void load());
</script>

<template>
  <section class="provider-run-review" v-loading="busy">
    <header>
      <div>
        <h2>服务商验证运行的生产门禁</h2>
        <p>技术批准不代表生产批准；人工审核只对当前明确绑定的素材生效。</p>
      </div>
      <el-select v-if="runs.length" :model-value="selected?.id" @change="(id:number) => choose(runs.find((run) => run.id === id)!)">
        <el-option v-for="run in runs" :key="run.id" :label="`运行 #${run.id} · ${statusLabel(run.status)}`" :value="run.id" />
      </el-select>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-empty v-else-if="!runs.length && !busy" description="该项目没有服务商验证运行记录" />
    <template v-if="selected">
      <div class="gate-cards">
        <article v-for="card in cards" :key="card[0]"><span>{{ card[0] }}</span><strong :class="String(card[1]).toLowerCase()">{{ statusLabel(String(card[1])) }}</strong></article>
      </div>
      <el-alert v-if="selected.technical_status === 'PASSED' && selected.production_status === 'BLOCKED'" title="技术流程已通过，但视觉或其他生产门禁未通过，不能进入生产。" type="warning" :closable="false" />
      <section class="scene-cut-panel">
        <h3>离线场景硬切证据</h3>
        <p><strong>{{ statusLabel(selected.scene_cut_check.status) }}</strong> · 算法版本 {{ selected.scene_cut_check.algorithm_version }}</p>
        <p>硬切：{{ selected.scene_cut_check.hard_cut_count }} · 待复核：{{ selected.scene_cut_check.review_candidate_count }}</p>
        <el-alert v-if="selected.scene_cut_check.hard_cut_count" title="意外场景硬切（UNEXPECTED_SCENE_CUT）会阻止生产，但不会修改技术任务结果。" type="error" :closable="false" />
        <p class="calibration">校准范围：{{ selected.scene_cut_check.calibration_scope === 'SYNTHETIC_FIXTURES_ONLY' ? '仅使用合成测试样本校准（SYNTHETIC_FIXTURES_ONLY）' : selected.scene_cut_check.calibration_scope }}；自动场景切换检测仅作为视觉证据，不改变技术任务结果。</p>
        <ul v-if="selected.scene_cut_check.events.length">
          <li v-for="event in selected.scene_cut_check.events" :key="`${event.asset_id}-${event.timestamp_seconds}`">
            素材 {{ event.asset_id }} · 时间点 {{ event.timestamp_seconds }} 秒 · 像素变化分数 {{ event.pixel_delta }} · 直方图变化分数 {{ event.histogram_delta }} · {{ event.classification }}
          </li>
        </ul>
      </section>
      <div class="run-layout">
        <section class="asset-panel">
          <h3>当前被审核素材</h3>
          <template v-if="selected.selected_review_asset">
            <video v-if="selected.selected_review_asset.type === 'PROJECT_RENDER' || selected.selected_review_asset.type === 'VIDEO'" controls :src="api.mediaUrl(selected.selected_review_asset.id)" />
            <img v-else :src="api.mediaUrl(selected.selected_review_asset.id)" alt="被审核素材预览" />
            <dl>
              <dt>素材 ID</dt><dd>{{ selected.selected_review_asset.id }}</dd>
              <dt>类型</dt><dd>{{ selected.selected_review_asset.type }}</dd>
              <dt>SHA-256</dt><dd>{{ selected.selected_review_asset.sha256.slice(0, 16) }}…</dd>
              <dt>创建时间</dt><dd>{{ formatDateTime(selected.selected_review_asset.created_at) }}</dd>
            </dl>
          </template>
          <p v-else>当前运行没有可审核的结果素材，生产状态保持“已阻断（BLOCKED）”。</p>
          <h3>阻断原因</h3>
          <el-tag v-for="blocker in selected.production_blockers" :key="blocker" type="danger">{{ productionBlockerLabel(blocker) }}</el-tag>
        </section>
        <section class="form-panel">
          <h3>追加人工视觉审核</h3>
          <el-radio-group v-model="form.decision"><el-radio value="APPROVED">已通过</el-radio><el-radio value="REJECTED">未通过</el-radio></el-radio-group>
          <el-checkbox-group v-if="form.decision === 'REJECTED'" v-model="form.reasons"><el-checkbox v-for="reason in reasonCodes" :key="reason" :value="reason">{{ reviewReasonLabel(reason) }}</el-checkbox></el-checkbox-group>
          <el-input v-model="form.notes" type="textarea" maxlength="2000" show-word-limit placeholder="审核说明" />
          <p v-if="validationMessage" class="validation">{{ validationMessage }}</p>
          <el-button type="primary" :loading="busy" :disabled="busy || !selected.selected_review_asset || Boolean(validationMessage)" @click="submit">提交审核</el-button>
        </section>
        <section class="history-panel">
          <h3>不可变审核历史</h3>
          <p v-if="selected.legacy_review_evidence">存在旧版 Asset 绑定报告证据；未伪造新的迁移审核记录。</p>
          <el-empty v-if="!history.length" description="尚无新版审核记录" />
          <article v-for="review in history" :key="review.id">
            <strong>{{ statusLabel(review.decision) }}</strong> · 素材 {{ review.asset_id }} · {{ review.reviewer_source }}
            <p>{{ formatDateTime(review.reviewed_at) }}</p><p>{{ review.reason_codes.map(reviewReasonLabel).join("，") }}</p>
          </article>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.provider-run-review{margin-bottom:18px;padding:16px;background:#fff;border:1px solid #d9e0ea;border-radius:10px}.provider-run-review header{display:flex;justify-content:space-between;gap:16px}.gate-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}.gate-cards article,.asset-panel,.form-panel,.history-panel,.scene-cut-panel{padding:12px;border:1px solid #e1e6ef;border-radius:8px}.scene-cut-panel{margin-top:12px}.scene-cut-panel .calibration{color:#667085;font-size:12px}.gate-cards span{display:block;color:#667085;font-size:12px}.gate-cards strong{display:block;margin-top:6px}.passed,.ready,.approved{color:#067647}.failed,.rejected,.blocked{color:#b42318}.pending,.warning{color:#b54708}.run-layout{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:14px}.asset-panel video,.asset-panel img{width:100%;max-height:240px;object-fit:contain;background:#111}.asset-panel dl{display:grid;grid-template-columns:100px 1fr}.asset-panel dd{margin:0;word-break:break-all}.form-panel .el-checkbox-group{display:flex;flex-direction:column;margin:12px 0}.validation{color:#b42318}.history-panel article{padding:8px 0;border-bottom:1px solid #e1e6ef}.asset-panel .el-tag{margin:3px}@media(max-width:1100px){.gate-cards,.run-layout{grid-template-columns:1fr}}
</style>
