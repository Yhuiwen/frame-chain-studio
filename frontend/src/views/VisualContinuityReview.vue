<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { useRoute } from "vue-router";

import { ApiError, api, type ProjectDetail, type VisualComparisonPair, type VisualContinuityReport, type VisualPreviewManifest } from "@/api/client";
import FrameComparison from "@/components/FrameComparison.vue";
import VisualReviewPlayer, { type TimelineMarker } from "@/components/VisualReviewPlayer.vue";

const route = useRoute();
const projectId = computed(() => Number(route.params.projectId || route.query.projectId || 22));
const reports = ref<VisualContinuityReport[]>([]);
const selected = ref<VisualContinuityReport | null>(null);
const manifest = ref<VisualPreviewManifest | null>(null);
const project = ref<ProjectDetail | null>(null);
const history = ref<Array<Record<string, unknown>>>([]);
const state = ref<"loading" | "empty" | "error" | "ready" | "submitting" | "conflict">("loading");
const errorMessage = ref("");
const onlyBlocked = ref(false);
const filter = ref("ALL");
const activePair = ref<VisualComparisonPair | null>(null);
const form = reactive({ status: "REJECTED" as "APPROVED" | "REJECTED", reasons: [] as string[], comment: "", checks: [] as string[] });
const reasons = ["CHARACTER_STYLE_DRIFT", "INTRA_SHOT_SCENE_CUT", "COMPOSITION_DISCONTINUITY", "SUBJECT_SCALE_DRIFT", "CAMERA_DRIFT", "ANCHOR_MISMATCH", "TARGET_KEYFRAME_MISMATCH", "CROSS_SHOT_SEAM_FAILURE", "EXTRA_OBJECT", "TEXT_OR_WATERMARK", "CHARACTER_DEFORMATION", "OTHER"];
const confirmations = ["已查看完整视频", "已查看异常候选前后帧", "已查看 Start Anchor 与首帧", "已查看 Target Keyframe 与尾帧", "已查看跨 Shot 接缝", "理解人工批准不能绕过自动生产门禁"];

const visibleReports = computed(() => reports.value.filter((item) =>
  (!onlyBlocked.value || item.production_gate_status === "BLOCKED") &&
  (filter.value === "ALL" || item.automatic_visual_status === filter.value || item.human_visual_status === filter.value),
));
const videoUrl = computed(() => {
  const render = project.value?.assets.find((item) => item.type === "PROJECT_RENDER");
  return render ? api.mediaUrl(render.id) : selected.value ? api.mediaUrl(selected.value.video_asset_id) : "";
});
const markers = computed<TimelineMarker[]>(() => {
  let offset = 0;
  const result: TimelineMarker[] = [];
  for (const report of [...reports.value].sort((a, b) => (a.shot_id || 0) - (b.shot_id || 0))) {
    if (offset > 0) result.push({ seconds: offset, label: "正式 Shot 边界", kind: "boundary" });
    const video = report.metrics.video as { duration?: number } | undefined;
    const candidates = report.metrics.sceneCutCandidates as Array<{ seconds?: number; decision?: string }> | undefined;
    for (const candidate of candidates || []) result.push({
      seconds: offset + Number(candidate.seconds || 0), label: "Shot 内场景切换",
      kind: candidate.decision === "UNEXPECTED_HARD_CUT" ? "confirmed" : "candidate",
    });
    offset += Number(video?.duration || 0);
  }
  return result;
});
const statusCards = computed(() => selected.value ? [
  ["技术任务", selected.value.technical_status], ["媒体验证", selected.value.technical_status],
  ["Lineage 连续性", selected.value.tail_frame_asset_id ? "PASSED" : "FAILED"],
  ["自动视觉", selected.value.automatic_visual_status], ["人工审核", selected.value.human_visual_status],
  ["生产门禁", selected.value.production_gate_status],
] : []);

async function load() {
  state.value = "loading";
  try {
    [reports.value, project.value] = await Promise.all([api.listVisualReports(projectId.value), api.getProject(projectId.value)]);
    if (!reports.value.length) { state.value = "empty"; return; }
    await selectReport(reports.value[0]); state.value = "ready";
  } catch (error) { handleError(error); }
}
async function selectReport(report: VisualContinuityReport) {
  selected.value = report;
  form.status = report.human_visual_status === "APPROVED" ? "APPROVED" : "REJECTED";
  form.reasons = [...report.rejection_reasons];
  [manifest.value, history.value] = await Promise.all([api.getVisualManifest(report.id), api.getVisualReviewHistory(report.id)]);
  activePair.value = manifest.value.comparisonPairs[0] || null;
}
function pairUrl(side: "left" | "right") {
  if (!selected.value || !activePair.value) return "";
  const id = activePair.value[`${side}AssetId`];
  let timestamp = activePair.value[`${side}Timestamp`];
  if (timestamp === null && activePair.value[`${side}Source`] === "VIDEO_FRAME") {
    timestamp = Number((selected.value.metrics.video as { duration?: number })?.duration || 0);
  }
  return activePair.value[`${side}Source`] === "VIDEO_FRAME"
    ? api.visualFrameUrl(selected.value.id, Number(timestamp || 0)) : id ? api.mediaUrl(id) : "";
}
async function reanalyze() {
  if (!selected.value) return;
  state.value = "submitting";
  try {
    await api.analyzeVisualReport({ video_asset_id: selected.value.video_asset_id, start_anchor_asset_id: selected.value.start_anchor_asset_id, target_keyframe_asset_id: selected.value.target_keyframe_asset_id, tail_frame_asset_id: selected.value.tail_frame_asset_id, analysis_version: selected.value.analysis_version });
    ElMessage.success("离线分析完成：已复用同版本报告，零 Provider 调用、零费用。"); await load();
  } catch (error) { handleError(error); }
}
async function submitReview() {
  if (!selected.value) return;
  if (form.checks.length !== confirmations.length) return ElMessage.warning("请完成全部审核确认项。");
  if (form.status === "REJECTED" && !form.reasons.length) return ElMessage.warning("REJECTED 至少选择一个原因。");
  if (form.reasons.includes("OTHER") && !form.comment.trim()) return ElMessage.warning("选择 OTHER 时必须填写说明。");
  state.value = "submitting";
  try {
    const updated = await api.reviewVisualReport(selected.value.id, { status: form.status, rejection_reasons: form.status === "REJECTED" ? form.reasons : [], comment: form.comment, reviewer: "local-operator", expected_report_hash: selected.value.report_hash, expected_updated_at: selected.value.updated_at });
    reports.value = reports.value.map((item) => item.id === updated.id ? updated : item); await selectReport(updated); state.value = "ready";
  } catch (error) { handleError(error); }
}
function handleError(error: unknown) {
  if (error instanceof ApiError && error.status === 409) state.value = "conflict"; else state.value = "error";
  const status = error instanceof ApiError ? error.status : 0;
  errorMessage.value = status === 403 ? "没有视觉审核权限。" : status === 404 ? "报告或媒体不存在。" : status === 409 ? "报告已被修改，请刷新后重试。" : error instanceof Error ? error.message : "加载失败";
}
watch(projectId, () => void load()); onMounted(() => void load());
</script>

<template>
  <main class="visual-review-page">
    <header class="review-header"><div><h1>视觉连续性审核</h1><p>供应商任务成功和视频可播放，不代表生产视觉质量通过。</p></div><el-button @click="reanalyze" :loading="state === 'submitting'">重新进行离线分析（不调用 TOAPIS、零费用）</el-button></header>
    <el-alert v-if="state === 'error' || state === 'conflict'" :title="errorMessage" type="error" show-icon />
    <el-empty v-else-if="state === 'empty'" description="该项目暂无视觉分析报告" />
    <div v-else class="review-layout" v-loading="state === 'loading'">
      <aside class="report-sidebar">
        <h2>Project {{ projectId }} 报告</h2><el-select v-model="filter"><el-option label="全部" value="ALL"/><el-option label="FAILED" value="FAILED"/><el-option label="INCONCLUSIVE" value="INCONCLUSIVE"/><el-option label="待人工审核" value="PENDING"/></el-select><el-checkbox v-model="onlyBlocked">只看 BLOCKED</el-checkbox>
        <button v-for="item in visibleReports" :key="item.id" class="report-item" :class="{active:selected?.id===item.id}" @click="selectReport(item)"><strong>Shot {{ item.shot_id }} · Asset {{ item.video_asset_id }}</strong><span>{{ item.analysis_version }} · {{ item.report_hash.slice(0, 10) }}</span><span>{{ item.automatic_visual_status }} / {{ item.human_visual_status }} / {{ item.production_gate_status }}</span></button>
      </aside>
      <section v-if="selected" class="review-main">
        <div class="status-grid"><article v-for="card in statusCards" :key="card[0]" class="status-card"><span>{{ card[0] }}</span><strong :class="String(card[1]).toLowerCase()">{{ card[1] }}</strong></article></div>
        <VisualReviewPlayer :src="videoUrl" :markers="markers" :fps="Number((selected.metrics.video as any)?.fps || 24)" />
        <section class="panel"><h2>帧对比工作区</h2><el-select v-model="activePair" value-key="kind"><el-option v-for="pair in manifest?.comparisonPairs" :key="pair.kind + pair.leftTimestamp" :label="pair.kind" :value="pair"/></el-select><FrameComparison v-if="activePair" :left-url="pairUrl('left')" :right-url="pairUrl('right')" :left-label="`${activePair.leftSource} · Asset ${activePair.leftAssetId ?? '-'} · ${activePair.leftTimestamp ?? '-'}s`" :right-label="`${activePair.rightSource} · Asset ${activePair.rightAssetId ?? '-'} · ${activePair.rightTimestamp ?? '尾帧'}s`" /></section>
        <section class="panel"><h2>自动指标详情</h2><el-descriptions :column="3" border><el-descriptions-item label="场景切换">{{ selected.scene_cut_status }}</el-descriptions-item><el-descriptions-item label="Anchor">{{ selected.anchor_match_status }}</el-descriptions-item><el-descriptions-item label="Target">{{ selected.target_match_status }}</el-descriptions-item><el-descriptions-item label="相机">{{ selected.camera_stability_status }}</el-descriptions-item><el-descriptions-item label="构图">{{ selected.composition_drift_status }}</el-descriptions-item><el-descriptions-item label="主体尺度">{{ selected.subject_scale_drift_status }}</el-descriptions-item><el-descriptions-item label="风格">{{ selected.style_drift_status }}</el-descriptions-item><el-descriptions-item label="跨 Shot">{{ manifest?.crossShotSeam?.status || selected.cross_shot_seam_status }}</el-descriptions-item></el-descriptions><p v-if="manifest?.crossShotSeam?.status === 'PASSED'">正式 Shot 接缝 lineage 通过，不是本次主要失败原因；Shot 内异常仍独立阻断。</p><p>启发式指标，不等同于语义主体识别。INCONCLUSIVE 表示证据不足，必须人工判断并继续阻断生产。</p><details><summary>原始数值与阈值</summary><pre>{{ JSON.stringify(selected.metrics, null, 2) }}</pre></details></section>
        <section class="panel"><h2>关键帧差异预算与 Prompt Contract</h2><p>TOO_SIMILAR：动作差异不足；TOO_DIFFERENT：容易重绘或跳切；INCONCLUSIVE：必须人工判断。</p><el-alert v-if="manifest?.promptContractWarning" :title="manifest.promptContractWarning" type="warning" :closable="false"/><pre v-else>{{ JSON.stringify(manifest?.promptContract, null, 2) }}</pre></section>
      </section>
      <aside v-if="selected" class="review-aside"><section class="panel"><h2>人工审核</h2><el-alert v-if="selected.human_visual_status === 'REJECTED'" title="历史 REJECTED 已锁定展示；本阶段不修改 Run 6 结论。" type="error" :closable="false"/><el-radio-group v-model="form.status"><el-radio value="APPROVED">APPROVED</el-radio><el-radio value="REJECTED">REJECTED</el-radio></el-radio-group><el-checkbox-group v-model="form.reasons"><el-checkbox v-for="reason in reasons" :key="reason" :value="reason">{{ reason }}</el-checkbox></el-checkbox-group><el-input v-model="form.comment" type="textarea" maxlength="2000" show-word-limit placeholder="纯文本审核说明"/><el-checkbox-group v-model="form.checks"><el-checkbox v-for="item in confirmations" :key="item" :value="item">{{ item }}</el-checkbox></el-checkbox-group><el-button type="primary" :disabled="selected.project_id === 22 && selected.human_visual_status === 'REJECTED'" @click="submitReview">提交人工审核</el-button><p v-if="form.status === 'APPROVED' && selected.automatic_visual_status !== 'PASSED'">人工 APPROVED 不能绕过自动失败；Production gate 仍为 BLOCKED。</p></section><section class="panel"><h2>拒绝原因</h2><el-tag v-for="reason in selected.rejection_reasons" :key="reason" type="danger">{{ reason }}</el-tag></section><section class="panel"><h2>审核历史</h2><p>分析版本 {{ selected.analysis_version }}<br/>Config {{ selected.config_hash.slice(0,12) }}<br/>Report {{ selected.report_hash.slice(0,12) }}</p><div v-for="event in history" :key="String(event.id)">{{ event.reviewed_at }} · {{ event.reviewer }} · {{ event.status }}</div></section><section class="panel gate"><h2>生产质量门禁</h2><strong>{{ selected.production_gate_status }}</strong><p>技术、媒体验证、自动视觉、人工审核与 lineage 必须全部通过。客户端无法提交 ALLOWED。</p></section></aside>
    </div>
  </main>
</template>

<style scoped>
.visual-review-page{min-height:100vh;padding:22px;background:#f3f5f8;color:#172033}.review-header{display:flex;justify-content:space-between;gap:18px;margin-bottom:18px}.review-layout{display:grid;grid-template-columns:260px minmax(520px,1fr) 330px;gap:16px}.report-sidebar,.panel,.status-card,.review-player{background:white;border:1px solid #d9e0ea;border-radius:10px;padding:14px}.report-sidebar{display:flex;flex-direction:column;gap:10px}.report-item{text-align:left;padding:10px;border:1px solid #d9e0ea;border-radius:8px;background:white;display:flex;flex-direction:column;gap:5px}.report-item.active{border-color:#2563eb;background:#eff6ff}.status-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-bottom:12px}.status-card span,.report-item span{font-size:12px;color:#667085}.status-card strong{display:block;margin-top:8px}.failed,.rejected,.blocked{color:#b42318}.passed,.allowed{color:#067647}.inconclusive,.pending{color:#b54708}.review-main,.review-aside{display:flex;flex-direction:column;gap:14px}.panel pre{white-space:pre-wrap;word-break:break-word;max-height:320px;overflow:auto;background:#f7f8fa;padding:10px}.review-aside .el-checkbox-group{display:flex;flex-direction:column;margin:12px 0}.review-aside .el-tag{margin:4px}.gate strong{font-size:28px;color:#b42318}@media(max-width:1100px){.review-layout{grid-template-columns:1fr}.status-grid{grid-template-columns:repeat(2,1fr)}}
</style>
