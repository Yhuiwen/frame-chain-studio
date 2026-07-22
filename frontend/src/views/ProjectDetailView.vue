<script setup lang="ts">
import {
  CaretRight,
  Check,
  Close,
  Picture,
  Plus,
  Refresh,
  RefreshRight,
  VideoPlay,
} from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { api, type GenerationStartOptions, type GenerationTask, type ProviderModelProfile, type ProviderProfile, type QualityCheckResult, type Shot, type ShotAssetSummary } from "@/api/client";
import ProjectWorkspaceLayout from "@/components/ProjectWorkspaceLayout.vue";
import { useProjectPolling } from "@/composables/useProjectPolling";
import { useStudioStore } from "@/stores/studio";
import { formatDateTime, statusLabel } from "@/constants/uiText";

const route = useRoute();
const store = useStudioStore();
const { startPolling, tick } = useProjectPolling();
const draggedShotId = ref<number | null>(null);
const deletingShotId = ref<number | null>(null);
const actionBusy = ref(false);
const taskActionBusyId = ref<number | null>(null);
const settingsBusy = ref(false);
const providerProfiles = ref<ProviderProfile[]>([]);
const providerModels = ref<Record<string, ProviderModelProfile[]>>({});
const renderBusy = ref(false);
const activeMediaStep = ref("start");
const qualityDetailsOpen = ref(true);
const expandedLogIds = ref<Set<number>>(new Set());
const startFrameInput = ref<HTMLInputElement | null>(null);
const targetKeyframeInput = ref<HTMLInputElement | null>(null);
const projectId = computed(() => Number(route.params.id));
const selected = computed(() => store.selectedShot);
const videos = computed(() => (selected.value ? store.assetsByShot(selected.value.id, "VIDEO") : []));
const selectedTasks = computed(() => store.tasksForSelected);
const selectedQualityChecks = computed(() => store.qualityChecksForSelected);
const qualitySummary = computed(() => {
  const checks = selectedQualityChecks.value;
  return {
    errors: checks.filter((item) => item.severity === "ERROR").length,
    warnings: checks.filter((item) => item.severity === "WARNING").length,
    infos: checks.filter((item) => item.severity === "INFO").length,
  };
});
const selectableProviders = computed(() => providerProfiles.value.filter(p => p.enabled && !p.archived_at));
const imageModels = computed(() => (providerModels.value[settingsForm.value.image_provider_id] ?? []).filter(m => m.generation_type === "IMAGE"));
const videoModels = computed(() => (providerModels.value[settingsForm.value.video_provider_id] ?? []).filter(m => m.generation_type === "VIDEO"));
const settingsForm = ref({
  image_provider_id: "",
  video_provider_id: "",
  image_model: "",
  video_model: "",
  default_aspect_ratio: "16:9",
  default_video_duration_seconds: null as number | null,
  default_seed: null as number | null,
  allow_capability_fallback: false,
});
const selectedTaskGroups = computed(() => {
  const requests = new Map((store.current?.requests ?? []).map((request) => [request.id, request]));
  return selectedTasks.value.map((task) => ({
    task,
    request: requests.get(task.generation_request_id) ?? null,
  }));
});
const latestRender = computed(() => [...(store.current?.renders ?? [])].reverse()[0] ?? null);
const generationWorkerOnline = computed(() => (store.workerStatus?.generation.online_count ?? 0) > 0);
const resultWorkerOnline = computed(() => (store.workerStatus?.result.online_count ?? 0) > 0);
const renderWorkerOnline = computed(() => (store.workerStatus?.render.online_count ?? 0) > 0);
const completedShotCount = computed(() => store.current?.completion.completed_shots ?? 0);
const totalShotCount = computed(() => store.current?.completion.total_shots ?? 0);
const settingsSummary = computed(() => {
  const imageProvider = selectableProviders.value.find(item => item.provider_key === settingsForm.value.image_provider_id);
  const videoProvider = selectableProviders.value.find(item => item.provider_key === settingsForm.value.video_provider_id);
  const imageModel = imageModels.value.find(item => item.model_key === settingsForm.value.image_model);
  const videoModel = videoModels.value.find(item => item.model_key === settingsForm.value.video_model);
  return `图片：${imageProvider?.display_name ?? "未选择"} / ${imageModel?.display_name ?? "未选择"} · 视频：${videoProvider?.display_name ?? "未选择"} / ${videoModel?.display_name ?? "未选择"} · 比例：${settingsForm.value.default_aspect_ratio || "未设置"} · 时长：${settingsForm.value.default_video_duration_seconds ?? "未设置"} 秒`;
});

onMounted(async () => {
  await store.loadProject(projectId.value);
  syncSettingsForm();
  await Promise.all([store.loadProviders(), store.refreshWorkers()]);
  if (typeof api.listProviderProfiles === "function") {
    providerProfiles.value = await api.listProviderProfiles();
    await Promise.all(providerProfiles.value.map(async p => { providerModels.value[p.provider_key] = await api.listProviderModels(p.id); }));
  }
  startPolling();
});

watch(selected, (shot) => {
  if (!shot) return;
  activeMediaStep.value = shot.status === "KEYFRAME_REVIEW" ? "keyframe" : shot.status === "VIDEO_REVIEW" ? "video" : shot.status === "COMPLETED" || shot.status === "TAIL_FRAME_LOCKED" ? "tail" : "start";
}, { immediate: true });

function syncSettingsForm() {
  const project = store.current;
  if (!project) return;
  settingsForm.value = {
    image_provider_id: project.image_provider_id ?? "",
    video_provider_id: project.video_provider_id ?? "",
    image_model: project.image_model ?? "",
    video_model: project.video_model ?? "",
    default_aspect_ratio: project.default_aspect_ratio ?? "16:9",
    default_video_duration_seconds: project.default_video_duration_seconds,
    default_seed: project.default_seed,
    allow_capability_fallback: false,
  };
}

async function saveGenerationSettings() {
  settingsBusy.value = true;
  try {
    await store.updateProjectSettings({
      image_provider_id: settingsForm.value.image_provider_id || null,
      video_provider_id: settingsForm.value.video_provider_id || null,
      image_model: settingsForm.value.image_model || null,
      video_model: settingsForm.value.video_model || null,
      default_aspect_ratio: settingsForm.value.default_aspect_ratio || null,
      default_video_duration_seconds: settingsForm.value.default_video_duration_seconds,
      default_seed: settingsForm.value.default_seed,
    });
    syncSettingsForm();
    ElMessage.success("生成设置已保存");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存生成设置失败");
  } finally {
    settingsBusy.value = false;
  }
}

function generationOptions(kind: "keyframe" | "video"): GenerationStartOptions {
  return {
    provider_id: kind === "keyframe" ? settingsForm.value.image_provider_id || null : settingsForm.value.video_provider_id || null,
    model: kind === "keyframe" ? settingsForm.value.image_model || null : settingsForm.value.video_model || null,
    aspect_ratio: settingsForm.value.default_aspect_ratio || null,
    seed: settingsForm.value.default_seed,
    duration_seconds: kind === "video" ? settingsForm.value.default_video_duration_seconds : null,
    allow_capability_fallback: settingsForm.value.allow_capability_fallback,
  };
}

function statusType(status: Shot["status"]) {
  if (status.includes("APPROVED") || status === "COMPLETED") return "success";
  if (status.includes("REVIEW")) return "warning";
  if (status.includes("GENERATING")) return "primary";
  return "info";
}

function sourceLabel(asset: ShotAssetSummary | null) {
  if (!asset) return "无";
  if (asset.source_type === "inherited") {
    const source = asset.source_shot_title ?? `Shot ${asset.source_shot_id ?? ""}`;
    return `继承自 ${source}`;
  }
  if (asset.source_type === "manual") return "手动指定";
  if (asset.source_type === "none") return "无";
  return "由当前镜头生成";
}

function imageProviderChanged() { if (!imageModels.value.some(m => m.model_key === settingsForm.value.image_model)) settingsForm.value.image_model = ""; }
function videoProviderChanged() { if (!videoModels.value.some(m => m.model_key === settingsForm.value.video_model)) settingsForm.value.video_model = ""; }

function qualityTagType(severity: QualityCheckResult["severity"]) {
  if (severity === "ERROR") return "danger";
  if (severity === "WARNING") return "warning";
  return "info";
}

function qualityLine(item: QualityCheckResult) {
  const score = item.score === null ? "" : `得分 ${formatMetric(item.score)}`;
  const threshold = item.threshold === null ? "" : `阈值 ${formatMetric(item.threshold)}`;
  return [score, threshold, item.algorithm_version].filter(Boolean).join(" · ");
}

function formatMetric(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(3);
}

async function rerunQualityChecks() {
  actionBusy.value = true;
  try {
    await store.runQualityChecks();
    ElMessage.success("质量检查已更新");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "质量检查失败");
  } finally {
    actionBusy.value = false;
  }
}

function assetFileName(asset: ShotAssetSummary | null) {
  return asset?.file_name ?? "暂无";
}

function assetIdLabel(asset: ShotAssetSummary | null) {
  return asset?.asset_id ?? "暂无";
}

function displayShotTitle(shot: Shot) {
  return /^Shot\s+\d+$/i.test(shot.title) ? `镜头 ${shot.sort_order + 1}` : shot.title;
}

function renderDisabledReason(reason: string | null | undefined) {
  if (!reason) return "";
  const missing = reason.match(/^Missing approved video for Shot (\d+)$/i);
  return missing ? `镜头 ${missing[1]} 还没有已通过的视频。` : reason;
}

function assetCreatedAt(asset: ShotAssetSummary | null) {
  return formatDateTime(asset?.created_at);
}

function selectedShotId() {
  return selected.value?.id ?? 0;
}

function navigateTo(path: string) {
  globalThis.location.assign(path);
}

async function archiveCurrentProject() {
  if (!store.current) return;
  try {
    await ElMessageBox.confirm(`移除项目“${store.current.name}”？之后可在已移除项目中恢复。`, "移除项目", { confirmButtonText: "移除", cancelButtonText: "取消", type: "warning" });
    await api.archiveProject(store.current.id);
    navigateTo("/");
  } catch { /* cancelled */ }
}

void [sourceLabel, assetFileName, assetIdLabel, assetCreatedAt];

async function guarded(action: () => Promise<unknown>, pollAfter = false) {
  actionBusy.value = true;
  try {
    await action();
    await store.refreshProjectDetail();
    if (pollAfter || store.hasActiveTasks) {
      startPolling();
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "操作失败");
  } finally {
    actionBusy.value = false;
  }
}

async function refreshProjectDetail() {
  await guarded(() => tick());
}

function canGenerateKeyframe(shot: Shot) {
  return shot.actions?.can_generate_keyframe ?? shot.status === "DRAFT";
}

function canGenerateVideo(shot: Shot) {
  return shot.actions?.can_generate_video ?? shot.status === "KEYFRAME_APPROVED";
}

function shortRemoteJobId(value: string | null) {
  if (!value) return "";
  return value.length <= 12 ? value : `${value.slice(0, 6)}...${value.slice(-4)}`;
}

function taskStage(task: GenerationTask) {
  if (task.status === "QUEUED") return "等待生成工作进程";
  if (task.status === "SUBMITTING") return "正在提交";
  if (task.status === "RUNNING") return task.processing_stage ? statusLabel(task.processing_stage) : "远端生成中";
  if (task.status === "RESULT_READY") return "等待结果工作进程";
  if (task.status === "PROCESSING_RESULT") return "正在下载并验证";
  if (task.status === "RETRY_WAIT") return "重试退避中";
  if (task.status === "CANCELLING") return "正在取消";
  return statusLabel(task.status);
}

async function deleteShot(shot: Shot, event: MouseEvent) {
  event.preventDefault();
  event.stopPropagation();
  try {
    await ElMessageBox.confirm(`删除“${shot.title || `镜头 ${shot.sort_order + 1}`}”后将无法恢复，是否继续？`, "确认删除镜头", {
      confirmButtonText: "确认删除",
      cancelButtonText: "取消",
      type: "warning",
    });
  } catch {
    return;
  }
  deletingShotId.value = shot.id;
  try {
    await store.deleteShot(shot.id);
    ElMessage.success("镜头已删除");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "删除镜头失败");
  } finally {
    deletingShotId.value = null;
  }
}

async function dropOn(target: Shot) {
  if (!store.current || draggedShotId.value === null || draggedShotId.value === target.id) return;
  const shots = [...store.current.shots];
  const from = shots.findIndex((shot) => shot.id === draggedShotId.value);
  const to = shots.findIndex((shot) => shot.id === target.id);
  const [shot] = shots.splice(from, 1);
  shots.splice(to, 0, shot);
  draggedShotId.value = null;
  await guarded(() => store.reorder(store.current?.id ?? projectId.value, shots));
}

function toggleLog(logId: number, event: MouseEvent) {
  event.preventDefault();
  event.stopPropagation();
  const next = new Set(expandedLogIds.value);
  if (next.has(logId)) next.delete(logId);
  else next.add(logId);
  expandedLogIds.value = next;
}

function idempotencyKey(action: string, taskId: number) {
  const randomPart = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `ui:${action}:${taskId}:${randomPart}`;
}

function taskType(task: GenerationTask) {
  if (task.status === "FAILED") return "danger";
  if (task.status === "CANCELLED") return "info";
  if (task.status === "SUCCEEDED") return "success";
  if (task.status === "RESULT_READY" || task.status === "PROCESSING_RESULT") return "primary";
  if (task.status === "RETRY_WAIT" || task.status === "CANCELLING") return "warning";
  return "primary";
}

async function cancelTask(task: GenerationTask) {
  try {
    await ElMessageBox.confirm("取消后，已经提交给服务商的远程任务可能仍会继续执行。", `确认取消任务 #${task.id}`, {
      confirmButtonText: "确认取消",
      cancelButtonText: "返回",
      type: "warning",
    });
  } catch {
    return;
  }
  taskActionBusyId.value = task.id;
  try {
    await api.cancelTask(task.id, "Cancelled from project task panel.", idempotencyKey("cancel", task.id));
    await store.refreshProjectDetail();
    startPolling();
    ElMessage.success("已提交取消请求");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "取消任务失败");
  } finally {
    taskActionBusyId.value = null;
  }
}

async function retryTask(task: GenerationTask) {
  try {
    await ElMessageBox.confirm("重试可能产生新的任务记录。真实服务商模式下可能产生费用。", `确认重试任务 #${task.id}`, {
      confirmButtonText: "确认重试", cancelButtonText: "返回", type: "warning",
    });
  } catch { return; }
  taskActionBusyId.value = task.id;
  try {
    await api.retryTask(task.id, "Manual retry from project task panel.", idempotencyKey("retry", task.id));
    await store.refreshProjectDetail();
    startPolling();
    ElMessage.success("重试任务已排队");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Retry failed");
  } finally {
    taskActionBusyId.value = null;
  }
}

async function createRender() {
  if (!store.current) return;
  renderBusy.value = true;
  try {
    await api.createProjectRender(store.current.id, idempotencyKey("render", store.current.id));
    await store.refreshProjectDetail();
    startPolling();
    ElMessage.success("Render queued");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Render failed");
  } finally {
    renderBusy.value = false;
  }
}

async function uploadAndSetStartFrame(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file || !store.current || !selected.value) return;
  await guarded(async () => {
    const asset = await api.uploadProjectImage(store.current?.id ?? projectId.value, file);
    await api.setStartFrame(selected.value?.id ?? 0, { action: "SELECT", asset_id: asset.id });
  });
  (event.target as HTMLInputElement).value = "";
}

async function uploadTargetKeyframe(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file || !store.current || !selected.value) return;
  await guarded(async () => {
    const asset = await api.uploadProjectImage(store.current?.id ?? projectId.value, file);
    await api.setTargetKeyframe(selected.value?.id ?? 0, { asset_id: asset.id });
  });
  (event.target as HTMLInputElement).value = "";
}
</script>

<template>
  <ProjectWorkspaceLayout :project-id="projectId" :project-name="store.current?.name || '项目工作台'" :project-status="completedShotCount === totalShotCount && totalShotCount ? '已完成' : '制作中'" page-title="项目工作台" :shot-id="selected?.id">
    <template #actions>
      <el-button native-type="button" :icon="Refresh" :loading="store.refreshing" @click="refreshProjectDetail">刷新</el-button>
      <el-button @click="archiveCurrentProject">移除项目</el-button>
    </template>
    <main class="workspace" v-loading="store.loading">
    <section class="workspace-intro">
      <div>
        <p>{{ store.current?.description || "包含审核、工作进程、服务商与最终渲染的连续性生成工作流。" }}</p>
        <div class="project-meta"><el-tag type="primary">{{ completedShotCount === totalShotCount && totalShotCount ? "已完成" : "制作中" }}</el-tag><span>{{ totalShotCount }} 个镜头</span><span>更新于 {{ formatDateTime(store.current?.updated_at) }}</span></div>
      </div>
    </section>

    <section class="ops-panel">
      <div class="settings-panel">
        <div class="panel-title">
          <h2>生成设置</h2>
          <el-button native-type="button" type="primary" :loading="settingsBusy" @click="saveGenerationSettings">
            保存设置
          </el-button>
        </div>
        <div class="settings-grid">
          <label>
            图片服务商
            <el-select v-model="settingsForm.image_provider_id" placeholder="选择图片服务商" clearable @change="imageProviderChanged">
              <el-option
                v-for="provider in selectableProviders"
                :key="provider.id"
                :label="provider.display_name"
                :value="provider.provider_key"
              />
            </el-select>
          </label>
          <label>
            视频服务商
            <el-select v-model="settingsForm.video_provider_id" placeholder="选择视频服务商" clearable @change="videoProviderChanged">
              <el-option
                v-for="provider in selectableProviders"
                :key="provider.id"
                :label="provider.display_name"
                :value="provider.provider_key"
              />
            </el-select>
          </label>
          <label>
            图片模型
            <el-select v-model="settingsForm.image_model" :disabled="!settingsForm.image_provider_id" placeholder="选择图片模型"><el-option v-for="model in imageModels" :key="model.id" :label="`${model.display_name} · ${model.remote_model || model.model_key}${model.enabled ? '' : ' · 已停用'}`" :value="model.model_key" :disabled="!model.enabled" /></el-select>
          </label>
          <label>
            视频模型
            <el-select v-model="settingsForm.video_model" :disabled="!settingsForm.video_provider_id" placeholder="选择视频模型"><el-option v-for="model in videoModels" :key="model.id" :label="`${model.display_name} · ${model.remote_model || model.model_key}${model.enabled ? '' : ' · 已停用'}`" :value="model.model_key" :disabled="!model.enabled" /></el-select>
          </label>
          <label>
            画面比例
            <el-input v-model="settingsForm.default_aspect_ratio" />
          </label>
          <label>
            时长（秒）
            <el-input-number v-model="settingsForm.default_video_duration_seconds" :min="0.1" :max="60" />
          </label>
          <label>
            随机种子
            <el-input-number v-model="settingsForm.default_seed" />
          </label>
          <label class="switch-row">
            允许连续性降级
            <el-switch v-model="settingsForm.allow_capability_fallback" />
          </label>
        </div>
        <p class="settings-summary">{{ settingsSummary }}</p>
      </div>
      <div class="worker-panel">
        <div class="panel-title">
          <h2>工作进度</h2>
          <el-button native-type="button" :icon="Refresh" :loading="store.workersRefreshing" @click="store.refreshWorkers">
            刷新工作状态
          </el-button>
        </div>
        <div class="worker-row">
          <el-tag :type="generationWorkerOnline ? 'success' : 'danger'">
            生成工作进程 {{ store.workerStatus?.generation.online_count ?? 0 }}/{{ store.workerStatus?.generation.total_count ?? 0 }}
          </el-tag>
          <span v-if="!generationWorkerOnline">启动命令：python -m app.workers.cli generation</span>
        </div>
        <div class="worker-row"><el-tag :type="renderWorkerOnline ? 'success' : 'danger'">渲染工作进程：{{ renderWorkerOnline ? '在线' : '离线' }}</el-tag></div>
        <div class="progress-summary"><span>当前镜头：{{ selected ? statusLabel(selected.status) : '暂无' }}</span><span>运行任务：{{ store.hasActiveTasks ? '有' : '无' }}</span><span>镜头进度：{{ completedShotCount }} / {{ totalShotCount }}</span><el-progress :percentage="totalShotCount ? Math.round(completedShotCount / totalShotCount * 100) : 0" /></div>
        <div class="worker-row">
          <el-tag :type="resultWorkerOnline ? 'success' : 'danger'">
            结果工作进程 {{ store.workerStatus?.result.online_count ?? 0 }}/{{ store.workerStatus?.result.total_count ?? 0 }}
          </el-tag>
          <span v-if="!resultWorkerOnline">启动命令：python -m app.workers.result_cli run</span>
        </div>
      </div>
    </section>

    <section class="layout">
      <aside class="timeline">
        <div class="timeline-header"><h2>镜头列表</h2><el-button type="primary" size="small" :icon="Plus" :loading="actionBusy" @click="guarded(() => store.createShot(projectId))">添加镜头</el-button></div>
        <div
          v-for="shot in store.current?.shots"
          :key="shot.id"
          class="timeline-item"
          :class="{ active: shot.id === selected?.id }"
          draggable="true"
          role="button"
          tabindex="0"
          @dragstart="draggedShotId = shot.id"
          @dragover.prevent
          @drop="dropOn(shot)"
          @click="store.selectShot(shot.id)"
        >
          <span class="order">{{ shot.sort_order + 1 }}</span>
          <span class="shot-title">{{ displayShotTitle(shot) }}</span>
          <el-tag size="small" :type="statusType(shot.status)">{{ statusLabel(shot.status) }}</el-tag>
          <div class="shot-flags"><span>{{ shot.approved_keyframe_asset_id ? '关键帧已通过' : '关键帧待处理' }}</span><span>{{ shot.approved_video_asset_id ? '视频已通过' : '视频待处理' }}</span><span>{{ shot.locked_tail_frame_asset_id ? '尾帧已锁定' : '尾帧未锁定' }}</span></div><el-dropdown trigger="click" @click.stop><el-button text aria-label="更多镜头操作">更多</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item class="delete-shot" @click="deleteShot(shot, $event)">删除镜头</el-dropdown-item></el-dropdown-menu></template></el-dropdown>
        </div>
      </aside>

      <section v-if="selected" class="review-grid">
        <div class="editor-panel">
          <div class="panel-title">
            <h2>{{ displayShotTitle(selected) }}</h2>
            <el-tag :type="statusType(selected.status)">{{ statusLabel(selected.status) }}</el-tag>
          </div>
          <div class="revision-meta">
            <el-tag size="small">第 {{ selected.spec_revision }} 版</el-tag>
            <el-tag size="small" type="info">{{ statusLabel(selected.start_frame_source_type) }}</el-tag>
            <span>关键帧 #{{ selected.approved_keyframe_asset_id ?? "无" }}</span>
            <span>视频 #{{ selected.approved_video_asset_id ?? "无" }}</span>
            <span>尾帧 #{{ selected.locked_tail_frame_asset_id ?? "无" }}</span>
          </div>
          <el-form label-position="top">
            <el-form-item label="标题">
              <el-input :model-value="selected.title" @change="store.updateSelectedShot({ title: String($event) })" />
            </el-form-item>
            <el-form-item label="描述">
              <el-input
                :model-value="selected.description"
                type="textarea"
                :rows="2"
                @change="store.reviseSelectedShot('Description changed', { description: String($event) })"
              />
            </el-form-item>
            <el-form-item label="时长（秒）">
              <el-input-number
                :model-value="selected.duration_seconds"
                :min="0.1"
                :max="60"
                @change="store.reviseSelectedShot('Duration changed', { duration_seconds: Number($event) })"
              />
            </el-form-item>
            <el-form-item label="提示词（Prompt）">
              <el-input
                :model-value="selected.prompt"
                type="textarea"
                :rows="4"
                @change="store.reviseSelectedShot('Prompt changed', { prompt: String($event) })"
              />
            </el-form-item>
            <el-form-item label="负面提示词">
              <el-input
                :model-value="selected.negative_prompt"
                type="textarea"
                :rows="3"
                @change="store.reviseSelectedShot('Negative prompt changed', { negative_prompt: String($event) })"
              />
            </el-form-item>
          </el-form>
        </div>

        <section class="shot-media-workspace">
        <nav class="media-steps" aria-label="镜头素材流程"><button :class="{active:activeMediaStep==='start'}" @click="activeMediaStep='start'">1 起始帧</button><button :class="{active:activeMediaStep==='keyframe'}" @click="activeMediaStep='keyframe'">2 目标关键帧</button><button :class="{active:activeMediaStep==='video'}" @click="activeMediaStep='video'">3 视频</button><button :class="{active:activeMediaStep==='tail'}" @click="activeMediaStep='tail'">4 已锁定尾帧</button></nav>

        <div v-show="activeMediaStep === 'start'" class="asset-panel media-detail">
          <div class="panel-title">
            <h2>起始帧</h2>
            <div class="button-row compact">
              <input ref="startFrameInput" class="hidden-input" type="file" accept="image/png,image/jpeg,image/webp" @change="uploadAndSetStartFrame" />
              <el-button native-type="button" size="small" :icon="Picture" @click="startFrameInput?.click()">
                上传
              </el-button>
              <el-button native-type="button" size="small" @click="guarded(() => api.setStartFrame(selectedShotId(), { action: 'CLEAR' }))">
                清除
              </el-button>
              <el-button native-type="button" size="small" @click="guarded(() => api.setStartFrame(selectedShotId(), { action: 'RESTORE_INHERITED' }))">
                恢复继承
              </el-button>
            </div>
          </div>
          <div class="asset-card">
            <el-image
              v-if="selected.start_frame"
              :src="selected.start_frame.url"
              :preview-src-list="[selected.start_frame.url]"
              fit="contain"
            >
              <template #error>
                <div class="asset-error">图片加载失败</div>
              </template>
            </el-image>
            <el-empty v-else description="暂无起始帧" />
            <dl>
              <dt>来源</dt>
              <dd>{{ sourceLabel(selected.start_frame) }}</dd>
              <dt>素材</dt>
              <dd>{{ assetFileName(selected.start_frame) }}</dd>
              <dt>ID</dt>
              <dd>{{ assetIdLabel(selected.start_frame) }}</dd>
              <dt>创建时间</dt>
              <dd>{{ assetCreatedAt(selected.start_frame) }}</dd>
            </dl>
          </div>
        </div>

        <div v-show="activeMediaStep === 'keyframe'" class="review-panel media-detail">
          <div class="panel-title">
            <h2>目标关键帧</h2>
            <input ref="targetKeyframeInput" class="hidden-input" type="file" accept="image/png,image/jpeg,image/webp" @change="uploadTargetKeyframe" />
            <el-button native-type="button" :icon="Picture" @click="targetKeyframeInput?.click()">
              上传
            </el-button>
            <el-button
              native-type="button"
              type="primary"
              :icon="Picture"
              :loading="actionBusy && selected.status === 'DRAFT'"
              :disabled="!canGenerateKeyframe(selected) || actionBusy"
              @click="guarded(() => store.runAction((shotId) => api.generateKeyframe(shotId, generationOptions('keyframe'))), true)"
            >
              生成关键帧
            </el-button>
          </div>
          <div class="asset-strip">
            <el-image
              v-if="selected.target_keyframe"
              :src="selected.target_keyframe.url"
              :preview-src-list="[selected.target_keyframe.url]"
              fit="contain"
            >
              <template #error>
                <div class="asset-error">关键帧加载失败</div>
              </template>
            </el-image>
            <el-empty v-else description="暂无关键帧" />
          </div>
          <div class="button-row">
            <el-button
              native-type="button"
              type="success"
              :icon="Check"
              :disabled="selected.status !== 'KEYFRAME_REVIEW' || actionBusy"
              @click="guarded(() => store.runAction(api.approveKeyframe))"
            >
              通过
            </el-button>
            <el-button
              native-type="button"
              :icon="Close"
              :disabled="selected.status !== 'KEYFRAME_REVIEW' || actionBusy"
              @click="guarded(() => store.runAction(api.rejectKeyframe))"
            >
              退回
            </el-button>
          </div>
        </div>

        <div v-show="activeMediaStep === 'video'" class="review-panel media-detail">
          <div class="panel-title">
            <h2>视频审核</h2>
            <el-button
              native-type="button"
              type="primary"
              :icon="VideoPlay"
              :loading="actionBusy && selected.status === 'KEYFRAME_APPROVED'"
              :disabled="!canGenerateVideo(selected) || actionBusy"
              @click="guarded(() => store.runAction((shotId) => api.generateVideo(shotId, generationOptions('video'))), true)"
            >
              生成视频
            </el-button>
          </div>
          <div class="asset-strip">
            <video v-for="asset in videos" :key="asset.id" controls :src="asset.url" />
            <div v-if="!videos.length" class="compact-empty"><strong>暂无视频</strong><span>生成完成后可在此预览和审核。</span></div>
          </div>
          <div class="quality-panel">
            <div class="quality-header">
              <strong>
                质量检查：{{ qualitySummary.warnings }} 个警告，{{ qualitySummary.errors }} 个错误，{{ qualitySummary.infos }} 个正常
              </strong>
              <el-button
                native-type="button"
                size="small"
                :icon="Refresh"
                :loading="actionBusy && selected.status === 'VIDEO_REVIEW'"
                :disabled="actionBusy || (selected.status !== 'VIDEO_REVIEW' && !selected.approved_video_asset_id)"
                @click="rerunQualityChecks"
              >
                重新检查
              </el-button>
              <el-button v-if="selectedQualityChecks.length" native-type="button" size="small" text @click="qualityDetailsOpen = !qualityDetailsOpen">{{ qualityDetailsOpen ? '收起详情' : '查看详情' }}</el-button>
            </div>
            <div v-if="qualityDetailsOpen && selectedQualityChecks.length" class="quality-list">
              <div v-for="item in selectedQualityChecks" :key="item.id" class="quality-row">
                <el-tag size="small" :type="qualityTagType(item.severity)" :title="item.severity">{{ statusLabel(item.severity) }}</el-tag>
                <div>
                  <strong>{{ item.check_type }}</strong>
                  <p>{{ item.message }}</p>
                  <span>{{ qualityLine(item) }}</span>
                </div>
              </div>
            </div>
            <p v-else class="quality-hint">{{ videos.length ? '质量检查详情已收起。' : '质量检查将在视频生成完成后运行。' }}</p>
          </div>
          <div class="button-row">
            <el-button
              native-type="button"
              type="success"
              :icon="Check"
              :disabled="selected.status !== 'VIDEO_REVIEW' || actionBusy"
              @click="guarded(() => store.runAction(api.approveVideo), true)"
            >
              通过并锁定尾帧
            </el-button>
            <el-button
              native-type="button"
              :icon="Close"
              :disabled="selected.status !== 'VIDEO_REVIEW' || actionBusy"
              @click="guarded(() => store.runAction(api.rejectVideo))"
            >
              退回
            </el-button>
          </div>
        </div>

        <div v-show="activeMediaStep === 'tail'" class="asset-panel media-detail">
          <div class="panel-title">
            <h2>已锁定尾帧</h2>
          </div>
          <div class="asset-card">
            <el-image
              v-if="selected.locked_tail_frame"
              :src="selected.locked_tail_frame.url"
              :preview-src-list="[selected.locked_tail_frame.url]"
              fit="contain"
            >
              <template #error>
                <div class="asset-error">尾帧加载失败</div>
              </template>
            </el-image>
            <el-empty v-else description="暂无锁定尾帧" />
            <dl>
              <dt>来源</dt>
              <dd>{{ sourceLabel(selected.locked_tail_frame) }}</dd>
              <dt>素材</dt>
              <dd>{{ assetFileName(selected.locked_tail_frame) }}</dd>
            </dl>
          </div>
        </div>
        </section>

        <div class="log-panel">
          <div class="panel-title">
            <h2>任务日志</h2>
            <el-button native-type="button" :icon="CaretRight" text @click="refreshProjectDetail">同步</el-button>
          </div>
          <div class="task-list">
            <div v-for="{ task, request } in selectedTaskGroups" :key="task.id" class="task-row">
              <div v-if="request" class="request-main">
                <strong>请求 #{{ request.id }} {{ statusLabel(request.kind) }}</strong>
                <span>{{ request.effective_provider_id ?? request.provider_name }}</span>
                <span v-if="request.model">模型 {{ request.model }}</span>
                <span v-if="request.generation_mode">生成模式 {{ statusLabel(request.generation_mode) }}</span>
              </div>
              <div class="task-main">
                <strong>#{{ task.id }} {{ statusLabel(task.task_type) }}</strong>
                <el-tag size="small" :type="taskType(task)">{{ task.status }}</el-tag>
              </div>
              <div class="task-meta">
                <span>{{ taskStage(task) }}</span>
                第 {{ task.attempt_number }} 次尝试 / 已重试 {{ task.retry_count }}/{{ task.max_attempts }} 次
                <span v-if="task.remote_status">远端状态 {{ statusLabel(task.remote_status) }}</span>
                <span v-if="task.remote_job_id">任务标识 {{ shortRemoteJobId(task.remote_job_id) }}</span>
                <span v-if="task.remote_progress !== null">进度 {{ Math.round(task.remote_progress * 100) }}%</span>
                <span v-if="task.next_retry_at">下次重试 {{ formatDateTime(task.next_retry_at) }}</span>
                <span v-if="task.next_result_retry_at">下次结果重试 {{ formatDateTime(task.next_result_retry_at) }}</span>
                <span v-if="task.next_poll_at">下次轮询 {{ formatDateTime(task.next_poll_at) }}</span>
                <span v-if="task.job_deadline_at">任务截止 {{ formatDateTime(task.job_deadline_at) }}</span>
                <span v-if="task.cancellation_deadline_at">取消截止 {{ formatDateTime(task.cancellation_deadline_at) }}</span>
                <span v-if="task.result_count">结果 {{ task.result_count }}</span>
                <span v-if="task.processing_status">处理状态 {{ statusLabel(task.processing_status) }}</span>
                <span v-if="task.result_asset_id">素材 #{{ task.result_asset_id }}</span>
                <span v-if="task.result_hosts.length">结果主机 {{ task.result_hosts.join(", ") }}</span>
              </div>
              <div v-if="task.error_code || task.error_message" class="task-error">
                {{ task.error_code ?? "ERROR" }}: {{ task.error_message ?? "" }}
              </div>
              <div class="task-actions">
                <el-button
                  v-if="task.can_cancel"
                  native-type="button"
                  size="small"
                  :icon="Close"
                  :loading="taskActionBusyId === task.id"
                  :disabled="taskActionBusyId !== null"
                  @click="cancelTask(task)"
                >
                  取消
                </el-button>
                <el-button
                  v-if="task.can_retry"
                  native-type="button"
                  size="small"
                  type="primary"
                  :icon="RefreshRight"
                  :loading="taskActionBusyId === task.id"
                  :disabled="taskActionBusyId !== null"
                  @click="retryTask(task)"
                >
                  Retry
                </el-button>
              </div>
            </div>
          </div>
          <el-timeline>
            <el-timeline-item v-for="log in store.logsForSelected" :key="log.id" :timestamp="log.created_at">
              <button type="button" class="log-row" @click="toggleLog(log.id, $event)">
                <strong>{{ log.level }}</strong>
                <span>{{ log.message }}</span>
              </button>
              <div v-if="expandedLogIds.has(log.id)" class="log-detail">
                request: {{ log.request_id ?? "none" }} 路 shot: {{ log.shot_id ?? "none" }}
              </div>
            </el-timeline-item>
          </el-timeline>
        </div>

        <div class="render-panel">
          <div class="panel-title">
            <h2>成片导出</h2>
            <el-button
              native-type="button"
              type="primary"
              :loading="renderBusy"
              :disabled="renderBusy || !store.current?.completion.can_render"
              @click="createRender"
            >
              生成最终成片
            </el-button>
          </div>
          <div class="render-summary">
            <span>已完成 {{ store.current?.completion.completed_shots ?? 0 }}/{{ store.current?.completion.total_shots ?? 0 }} 个镜头</span>
            <span>预计 {{ Math.round(store.current?.completion.estimated_duration_seconds ?? 0) }} 秒</span>
            <span v-if="store.current?.completion.render_disabled_reason">{{ renderDisabledReason(store.current.completion.render_disabled_reason) }}</span>
          </div>
          <div v-if="latestRender" class="render-card">
            <div class="task-main">
              <strong>渲染 #{{ latestRender.id }} v{{ latestRender.render_version }}</strong>
              <el-tag size="small" :type="latestRender.status === 'SUCCEEDED' ? 'success' : latestRender.status === 'FAILED' ? 'danger' : 'primary'">
                {{ statusLabel(latestRender.status) }}
              </el-tag>
            </div>
            <div class="task-meta">
              <span>{{ statusLabel(latestRender.current_stage) }}</span>
              <span>{{ Math.round(latestRender.progress * 100) }}%</span>
              <span v-if="latestRender.error_code">{{ latestRender.error_code }}: {{ latestRender.error_message }}</span>
            </div>
            <video v-if="latestRender.output_url" controls :src="latestRender.output_url" />
            <a v-if="latestRender.output_url" :href="latestRender.output_url" download>下载最终视频</a>
          </div>
        </div>
      </section>
    </section>
    </main>
  </ProjectWorkspaceLayout>
</template>

<style scoped>
.workspace { width: 100%; min-height: 0; padding: 20px 24px 48px; position: relative; overflow: visible; }
.workspace-intro { margin-bottom: 18px; }
.project-meta,.progress-summary,.shot-flags { display:flex; flex-wrap:wrap; align-items:center; gap:10px; color:var(--muted); font-size:13px; margin-top:10px; }
.progress-summary { display:grid; align-items:stretch; }
.settings-summary { margin-top:14px; padding:10px; background:var(--surface-soft); border-radius:8px; }
.timeline { max-height:720px; overflow:auto; position:sticky; top:18px; }
.timeline-header { position:sticky; top:-12px; z-index:2; background:var(--surface); display:flex; justify-content:space-between; align-items:center; padding:8px 0 12px; }
.timeline-item { grid-template-columns:34px minmax(0,1fr) auto; }
.shot-flags { grid-column:2 / -1; margin:0; gap:6px; font-size:11px; }
.shot-media-workspace { grid-column: 2; min-width: 0; height: 600px; min-height: 600px; max-height: 600px; display: grid; grid-template-rows: auto minmax(0, 1fr); overflow: hidden; }
.media-steps { display:grid; grid-template-columns:repeat(4,minmax(126px,1fr)); gap:8px; padding:12px; background:var(--surface); border:1px solid var(--border); border-radius:12px; overflow-x:auto; }
.media-steps button { border:1px solid var(--border); border-radius:8px; padding:10px 6px; background:var(--surface-soft); cursor:pointer; }
.media-steps button.active { border-color:var(--primary); color:var(--primary); background:#edf3ff; font-weight:700; }
.media-detail { min-width: 0; min-height: 0; height: 100%; overflow: hidden; display: grid; grid-template-rows: auto minmax(0, 1fr) auto; }
.asset-strip, .asset-card { min-width: 0; min-height: 0; height: 100%; overflow: hidden; }
.asset-strip video, .asset-strip :deep(.el-image), .asset-card :deep(.el-image) { width: 100%; height: 100%; max-height: 100%; object-fit: contain; }
.compact-empty { height: 100%; display: grid; place-content: center; gap: 6px; text-align: center; color: var(--muted); }
.editor-panel { grid-row:1 / span 2; }
.render-panel { border-left:4px solid var(--primary) !important; }
.task-list {
  display: grid;
  gap: 10px;
  margin-bottom: 16px;
}

.ops-panel {
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr);
  margin: 0 0 18px;
}

.settings-panel,
.worker-panel {
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  padding: 14px;
}

.settings-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(4, minmax(140px, 1fr));
}

.settings-grid label {
  color: var(--el-text-color-secondary);
  display: grid;
  font-size: 12px;
  gap: 6px;
}

.switch-row {
  align-content: end;
}

.worker-row,
.request-main {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.worker-row {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: 10px;
}

.request-main {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-bottom: 8px;
}

.revision-meta {
  align-items: center;
  color: var(--el-text-color-secondary);
  display: flex;
  flex-wrap: wrap;
  font-size: 12px;
  gap: 8px;
  margin: 0 0 12px;
}

.task-row {
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  padding: 10px;
}

.render-panel {
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  grid-column: 1 / -1;
  padding: 14px;
}

.render-summary {
  color: var(--el-text-color-secondary);
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 10px;
}

.render-card video {
  display: block;
  margin-top: 10px;
  max-height: 360px;
  width: 100%;
}

.task-main,
.task-actions {
  align-items: center;
  display: flex;
  gap: 8px;
  justify-content: space-between;
}

.task-meta {
  color: var(--el-text-color-secondary);
  display: flex;
  flex-wrap: wrap;
  font-size: 12px;
  gap: 8px;
  margin-top: 6px;
}

.task-error {
  color: var(--el-color-danger);
  font-size: 12px;
  margin-top: 6px;
  overflow-wrap: anywhere;
}

.task-actions {
  justify-content: flex-start;
  margin-top: 8px;
}

.quality-panel {
  border-top: 1px solid var(--el-border-color);
  display: grid;
  gap: 10px;
  padding-top: 12px;
  min-height: 0;
  max-height: 132px;
  overflow: auto;
}

.quality-header {
  align-items: center;
  display: flex;
  gap: 12px;
  justify-content: space-between;
}

.quality-list {
  display: grid;
  gap: 8px;
}
.quality-hint { margin: 0; color: var(--el-text-color-secondary); font-size: 12px; }

.quality-row {
  align-items: flex-start;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  display: grid;
  gap: 8px;
  grid-template-columns: auto 1fr;
  padding: 8px;
}

.quality-row p {
  margin: 2px 0;
}

.quality-row span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.compact {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.hidden-input {
  display: none;
}

@media (max-width: 900px) {
  .workspace { padding: 14px; }
  .ops-panel,
  .settings-grid {
    grid-template-columns: 1fr;
  }
  .shot-media-workspace { grid-column: 1; height: 560px; min-height: 560px; max-height: 560px; }
  .editor-panel { grid-row:auto; }
  .timeline { position:static; max-height:300px; }
}
</style>
