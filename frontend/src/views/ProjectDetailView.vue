<script setup lang="ts">
import {
  CaretRight,
  Check,
  Close,
  Delete,
  Picture,
  Plus,
  Refresh,
  RefreshRight,
  VideoPlay,
} from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { api, type GenerationStartOptions, type GenerationTask, type QualityCheckResult, type Shot, type ShotAssetSummary } from "@/api/client";
import { useProjectPolling } from "@/composables/useProjectPolling";
import { useStudioStore } from "@/stores/studio";

const route = useRoute();
const store = useStudioStore();
const { startPolling, tick } = useProjectPolling();
const draggedShotId = ref<number | null>(null);
const deletingShotId = ref<number | null>(null);
const actionBusy = ref(false);
const taskActionBusyId = ref<number | null>(null);
const settingsBusy = ref(false);
const renderBusy = ref(false);
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
const configuredProviders = computed(() => store.providers.filter((provider) => provider.configured));
const imageProviders = computed(() => configuredProviders.value.filter((provider) => provider.capabilities.text_to_image));
const videoProviders = computed(() => configuredProviders.value.filter((provider) => provider.capabilities.image_to_video));
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

onMounted(async () => {
  await store.loadProject(projectId.value);
  syncSettingsForm();
  await Promise.all([store.loadProviders(), store.refreshWorkers()]);
  startPolling();
});

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
    ElMessage.success("Generation settings saved");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Save settings failed");
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
  if (!asset) return "None";
  if (asset.source_type === "inherited") {
    const source = asset.source_shot_title ?? `Shot ${asset.source_shot_id ?? ""}`;
    return `继承自 ${source}`;
  }
  if (asset.source_type === "manual") return "Manual";
  if (asset.source_type === "none") return "None";
  return "Generated by this Shot";
}

function qualityTagType(severity: QualityCheckResult["severity"]) {
  if (severity === "ERROR") return "danger";
  if (severity === "WARNING") return "warning";
  return "info";
}

function qualityLine(item: QualityCheckResult) {
  const score = item.score === null ? "" : `score ${formatMetric(item.score)}`;
  const threshold = item.threshold === null ? "" : `threshold ${formatMetric(item.threshold)}`;
  return [score, threshold, item.algorithm_version].filter(Boolean).join(" · ");
}

function formatMetric(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(3);
}

async function rerunQualityChecks() {
  actionBusy.value = true;
  try {
    await store.runQualityChecks();
    ElMessage.success("Quality checks updated");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Quality checks failed");
  } finally {
    actionBusy.value = false;
  }
}

function assetFileName(asset: ShotAssetSummary | null) {
  return asset?.file_name ?? "none";
}

function assetIdLabel(asset: ShotAssetSummary | null) {
  return asset?.asset_id ?? "none";
}

function assetCreatedAt(asset: ShotAssetSummary | null) {
  return asset?.created_at ?? "none";
}

function selectedShotId() {
  return selected.value?.id ?? 0;
}

function navigateTo(path: string) {
  globalThis.location.assign(path);
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
  if (task.status === "QUEUED") return "Waiting for GenerationWorker";
  if (task.status === "SUBMITTING") return "Submitting";
  if (task.status === "RUNNING") return task.processing_stage ?? "Remote generation";
  if (task.status === "RESULT_READY") return "Waiting for ResultWorker";
  if (task.status === "PROCESSING_RESULT") return "Downloading and validating";
  if (task.status === "RETRY_WAIT") return "Retry backoff";
  if (task.status === "CANCELLING") return "Cancelling";
  return task.status;
}

async function deleteShot(shot: Shot, event: MouseEvent) {
  event.preventDefault();
  event.stopPropagation();
  try {
    await ElMessageBox.confirm(`Delete ${shot.title || `Shot ${shot.sort_order + 1}`}?`, "Delete Shot", {
      confirmButtonText: "Delete",
      cancelButtonText: "Cancel",
      type: "warning",
    });
  } catch {
    return;
  }
  deletingShotId.value = shot.id;
  try {
    await store.deleteShot(shot.id);
    ElMessage.success("Shot deleted");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Delete failed");
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
    await ElMessageBox.confirm(`Cancel task #${task.id}?`, "Cancel Task", {
      confirmButtonText: "Cancel Task",
      cancelButtonText: "Keep Running",
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
    ElMessage.success("Cancel requested");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Cancel failed");
  } finally {
    taskActionBusyId.value = null;
  }
}

async function retryTask(task: GenerationTask) {
  taskActionBusyId.value = task.id;
  try {
    await api.retryTask(task.id, "Manual retry from project task panel.", idempotencyKey("retry", task.id));
    await store.refreshProjectDetail();
    startPolling();
    ElMessage.success("Retry queued");
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
  <main class="workspace" v-loading="store.loading">
    <section class="workspace-header">
      <div>
        <h1>{{ store.current?.name }}</h1>
        <p>{{ store.current?.description || "Continuity-aware generation workflow with review, workers, providers, and render." }}</p>
      </div>
      <div class="header-actions">
        <el-button native-type="button" @click="navigateTo(`/projects/${projectId}/library`)">
          Library
        </el-button>
        <el-button native-type="button" @click="navigateTo(`/projects/${projectId}/scripts`)">
          Scripts
        </el-button>
        <el-button native-type="button" @click="navigateTo(`/projects/${projectId}/usage`)">
          Usage
        </el-button>
        <el-button native-type="button" @click="navigateTo('/settings/providers')">
          Providers
        </el-button>
        <el-button
          v-if="selected"
          native-type="button"
          @click="navigateTo(`/projects/${projectId}/shot/${selected.id}/spec`)"
        >
          Shot Spec
        </el-button>
        <el-button native-type="button" @click="navigateTo(`/projects/${projectId}/visual-review`)">视觉连续性审核</el-button>
        <el-button native-type="button" :icon="Refresh" :loading="store.refreshing" @click="refreshProjectDetail">
          刷新
        </el-button>
        <el-button
          native-type="button"
          type="primary"
          :icon="Plus"
          :loading="actionBusy"
          @click="guarded(() => store.createShot(projectId))"
        >
          添加镜头
        </el-button>
      </div>
    </section>

    <section class="ops-panel">
      <div class="settings-panel">
        <div class="panel-title">
          <h2>Generation Settings</h2>
          <el-button native-type="button" type="primary" :loading="settingsBusy" @click="saveGenerationSettings">
            Save
          </el-button>
        </div>
        <div class="settings-grid">
          <label>
            Image Provider
            <el-select v-model="settingsForm.image_provider_id" placeholder="System default" clearable>
              <el-option
                v-for="provider in imageProviders"
                :key="provider.provider_id"
                :label="provider.display_name"
                :value="provider.provider_id"
              />
            </el-select>
          </label>
          <label>
            Video Provider
            <el-select v-model="settingsForm.video_provider_id" placeholder="System default" clearable>
              <el-option
                v-for="provider in videoProviders"
                :key="provider.provider_id"
                :label="provider.display_name"
                :value="provider.provider_id"
              />
            </el-select>
          </label>
          <label>
            Image Model
            <el-input v-model="settingsForm.image_model" />
          </label>
          <label>
            Video Model
            <el-input v-model="settingsForm.video_model" />
          </label>
          <label>
            Aspect Ratio
            <el-input v-model="settingsForm.default_aspect_ratio" />
          </label>
          <label>
            Duration
            <el-input-number v-model="settingsForm.default_video_duration_seconds" :min="0.1" :max="60" />
          </label>
          <label>
            Seed
            <el-input-number v-model="settingsForm.default_seed" />
          </label>
          <label class="switch-row">
            Allow continuity fallback
            <el-switch v-model="settingsForm.allow_capability_fallback" />
          </label>
        </div>
      </div>
      <div class="worker-panel">
        <div class="panel-title">
          <h2>Workers</h2>
          <el-button native-type="button" text :loading="store.workersRefreshing" @click="store.refreshWorkers">
            Refresh
          </el-button>
        </div>
        <div class="worker-row">
          <el-tag :type="generationWorkerOnline ? 'success' : 'danger'">
            Generation {{ store.workerStatus?.generation.online_count ?? 0 }}/{{ store.workerStatus?.generation.total_count ?? 0 }}
          </el-tag>
          <span v-if="!generationWorkerOnline">Start: python -m app.workers.cli generation</span>
        </div>
        <div class="worker-row">
          <el-tag :type="resultWorkerOnline ? 'success' : 'danger'">
            Result {{ store.workerStatus?.result.online_count ?? 0 }}/{{ store.workerStatus?.result.total_count ?? 0 }}
          </el-tag>
          <span v-if="!resultWorkerOnline">Start: python -m app.workers.result_cli run</span>
        </div>
      </div>
    </section>

    <section class="layout">
      <aside class="timeline">
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
          <span class="shot-title">{{ shot.title }}</span>
          <el-tag size="small" :type="statusType(shot.status)">{{ shot.status }}</el-tag>
          <el-button
            class="delete-shot"
            native-type="button"
            text
            type="danger"
            :icon="Delete"
            :loading="deletingShotId === shot.id"
            @click="deleteShot(shot, $event)"
          >
            删除 Shot
          </el-button>
        </div>
      </aside>

      <section v-if="selected" class="review-grid">
        <div class="editor-panel">
          <div class="panel-title">
            <h2>{{ selected.title }}</h2>
            <el-tag :type="statusType(selected.status)">{{ selected.status }}</el-tag>
          </div>
          <div class="revision-meta">
            <el-tag size="small">rev {{ selected.spec_revision }}</el-tag>
            <el-tag size="small" type="info">{{ selected.start_frame_source_type }}</el-tag>
            <span>keyframe #{{ selected.approved_keyframe_asset_id ?? "none" }}</span>
            <span>video #{{ selected.approved_video_asset_id ?? "none" }}</span>
            <span>tail #{{ selected.locked_tail_frame_asset_id ?? "none" }}</span>
          </div>
          <el-form label-position="top">
            <el-form-item label="Title">
              <el-input :model-value="selected.title" @change="store.updateSelectedShot({ title: String($event) })" />
            </el-form-item>
            <el-form-item label="Description">
              <el-input
                :model-value="selected.description"
                type="textarea"
                :rows="2"
                @change="store.reviseSelectedShot('Description changed', { description: String($event) })"
              />
            </el-form-item>
            <el-form-item label="Duration">
              <el-input-number
                :model-value="selected.duration_seconds"
                :min="0.1"
                :max="60"
                @change="store.reviseSelectedShot('Duration changed', { duration_seconds: Number($event) })"
              />
            </el-form-item>
            <el-form-item label="Prompt">
              <el-input
                :model-value="selected.prompt"
                type="textarea"
                :rows="4"
                @change="store.reviseSelectedShot('Prompt changed', { prompt: String($event) })"
              />
            </el-form-item>
            <el-form-item label="Negative Prompt">
              <el-input
                :model-value="selected.negative_prompt"
                type="textarea"
                :rows="3"
                @change="store.reviseSelectedShot('Negative prompt changed', { negative_prompt: String($event) })"
              />
            </el-form-item>
          </el-form>
        </div>

        <div class="asset-panel">
          <div class="panel-title">
            <h2>起始帧</h2>
            <div class="button-row compact">
              <input ref="startFrameInput" class="hidden-input" type="file" accept="image/png,image/jpeg,image/webp" @change="uploadAndSetStartFrame" />
              <el-button native-type="button" size="small" :icon="Picture" @click="startFrameInput?.click()">
                Upload
              </el-button>
              <el-button native-type="button" size="small" @click="guarded(() => api.setStartFrame(selectedShotId(), { action: 'CLEAR' }))">
                Clear
              </el-button>
              <el-button native-type="button" size="small" @click="guarded(() => api.setStartFrame(selectedShotId(), { action: 'RESTORE_INHERITED' }))">
                Inherit
              </el-button>
            </div>
          </div>
          <div class="asset-card">
            <el-image
              v-if="selected.start_frame"
              :src="selected.start_frame.url"
              :preview-src-list="[selected.start_frame.url]"
              fit="cover"
            >
              <template #error>
                <div class="asset-error">Image failed to load</div>
              </template>
            </el-image>
            <el-empty v-else description="No start frame" />
            <dl>
              <dt>Source</dt>
              <dd>{{ sourceLabel(selected.start_frame) }}</dd>
              <dt>Asset</dt>
              <dd>{{ assetFileName(selected.start_frame) }}</dd>
              <dt>ID</dt>
              <dd>{{ assetIdLabel(selected.start_frame) }}</dd>
              <dt>Created</dt>
              <dd>{{ assetCreatedAt(selected.start_frame) }}</dd>
            </dl>
          </div>
        </div>

        <div class="review-panel">
          <div class="panel-title">
            <h2>Target Keyframe</h2>
            <input ref="targetKeyframeInput" class="hidden-input" type="file" accept="image/png,image/jpeg,image/webp" @change="uploadTargetKeyframe" />
            <el-button native-type="button" :icon="Picture" @click="targetKeyframeInput?.click()">
              Upload
            </el-button>
            <el-button
              native-type="button"
              type="primary"
              :icon="Picture"
              :loading="actionBusy && selected.status === 'DRAFT'"
              :disabled="!canGenerateKeyframe(selected) || actionBusy"
              @click="guarded(() => store.runAction((shotId) => api.generateKeyframe(shotId, generationOptions('keyframe'))), true)"
            >
              Generate Keyframe
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
                <div class="asset-error">Keyframe failed to load</div>
              </template>
            </el-image>
            <el-empty v-else description="No keyframe" />
          </div>
          <div class="button-row">
            <el-button
              native-type="button"
              type="success"
              :icon="Check"
              :disabled="selected.status !== 'KEYFRAME_REVIEW' || actionBusy"
              @click="guarded(() => store.runAction(api.approveKeyframe))"
            >
              Approve
            </el-button>
            <el-button
              native-type="button"
              :icon="Close"
              :disabled="selected.status !== 'KEYFRAME_REVIEW' || actionBusy"
              @click="guarded(() => store.runAction(api.rejectKeyframe))"
            >
              Reject
            </el-button>
          </div>
        </div>

        <div class="review-panel">
          <div class="panel-title">
            <h2>Video Review</h2>
            <el-button
              native-type="button"
              type="primary"
              :icon="VideoPlay"
              :loading="actionBusy && selected.status === 'KEYFRAME_APPROVED'"
              :disabled="!canGenerateVideo(selected) || actionBusy"
              @click="guarded(() => store.runAction((shotId) => api.generateVideo(shotId, generationOptions('video'))), true)"
            >
              Generate Video
            </el-button>
          </div>
          <div class="asset-strip">
            <video v-for="asset in videos" :key="asset.id" controls :src="asset.url" />
            <el-empty v-if="!videos.length" description="No video" />
          </div>
          <div class="quality-panel">
            <div class="quality-header">
              <strong>
                Quality checks: {{ qualitySummary.warnings }} warnings, {{ qualitySummary.errors }} errors, {{ qualitySummary.infos }} normal
              </strong>
              <el-button
                native-type="button"
                size="small"
                :icon="Refresh"
                :loading="actionBusy && selected.status === 'VIDEO_REVIEW'"
                :disabled="actionBusy || (selected.status !== 'VIDEO_REVIEW' && !selected.approved_video_asset_id)"
                @click="rerunQualityChecks"
              >
                Rerun
              </el-button>
            </div>
            <div v-if="selectedQualityChecks.length" class="quality-list">
              <div v-for="item in selectedQualityChecks" :key="item.id" class="quality-row">
                <el-tag size="small" :type="qualityTagType(item.severity)">{{ item.severity }}</el-tag>
                <div>
                  <strong>{{ item.check_type }}</strong>
                  <p>{{ item.message }}</p>
                  <span>{{ qualityLine(item) }}</span>
                </div>
              </div>
            </div>
            <el-empty v-else description="No current quality checks" />
          </div>
          <div class="button-row">
            <el-button
              native-type="button"
              type="success"
              :icon="Check"
              :disabled="selected.status !== 'VIDEO_REVIEW' || actionBusy"
              @click="guarded(() => store.runAction(api.approveVideo), true)"
            >
              Approve and Lock Tail
            </el-button>
            <el-button
              native-type="button"
              :icon="Close"
              :disabled="selected.status !== 'VIDEO_REVIEW' || actionBusy"
              @click="guarded(() => store.runAction(api.rejectVideo))"
            >
              Reject
            </el-button>
          </div>
        </div>

        <div class="asset-panel">
          <div class="panel-title">
            <h2>Locked Tail Frame</h2>
          </div>
          <div class="asset-card">
            <el-image
              v-if="selected.locked_tail_frame"
              :src="selected.locked_tail_frame.url"
              :preview-src-list="[selected.locked_tail_frame.url]"
              fit="cover"
            >
              <template #error>
                <div class="asset-error">Tail frame failed to load</div>
              </template>
            </el-image>
            <el-empty v-else description="No locked tail frame" />
            <dl>
              <dt>Source</dt>
              <dd>{{ sourceLabel(selected.locked_tail_frame) }}</dd>
              <dt>Asset</dt>
              <dd>{{ assetFileName(selected.locked_tail_frame) }}</dd>
            </dl>
          </div>
        </div>

        <div class="log-panel">
          <div class="panel-title">
            <h2>任务日志</h2>
            <el-button native-type="button" :icon="CaretRight" text @click="refreshProjectDetail">同步</el-button>
          </div>
          <div class="task-list">
            <div v-for="{ task, request } in selectedTaskGroups" :key="task.id" class="task-row">
              <div v-if="request" class="request-main">
                <strong>Request #{{ request.id }} {{ request.kind }}</strong>
                <span>{{ request.effective_provider_id ?? request.provider_name }}</span>
                <span v-if="request.model">model {{ request.model }}</span>
                <span v-if="request.generation_mode">mode {{ request.generation_mode }}</span>
              </div>
              <div class="task-main">
                <strong>#{{ task.id }} {{ task.task_type }}</strong>
                <el-tag size="small" :type="taskType(task)">{{ task.status }}</el-tag>
              </div>
              <div class="task-meta">
                <span>{{ taskStage(task) }}</span>
                attempt {{ task.attempt_number }} / retries {{ task.retry_count }}/{{ task.max_attempts }}
                <span v-if="task.remote_status">remote {{ task.remote_status }}</span>
                <span v-if="task.remote_job_id">job {{ shortRemoteJobId(task.remote_job_id) }}</span>
                <span v-if="task.remote_progress !== null">progress {{ Math.round(task.remote_progress * 100) }}%</span>
                <span v-if="task.next_retry_at">next retry {{ task.next_retry_at }}</span>
                <span v-if="task.next_result_retry_at">next result retry {{ task.next_result_retry_at }}</span>
                <span v-if="task.next_poll_at">next poll {{ task.next_poll_at }}</span>
                <span v-if="task.job_deadline_at">job deadline {{ task.job_deadline_at }}</span>
                <span v-if="task.cancellation_deadline_at">cancel deadline {{ task.cancellation_deadline_at }}</span>
                <span v-if="task.result_count">results {{ task.result_count }}</span>
                <span v-if="task.processing_status">processing {{ task.processing_status }}</span>
                <span v-if="task.result_asset_id">asset #{{ task.result_asset_id }}</span>
                <span v-if="task.result_hosts.length">hosts {{ task.result_hosts.join(", ") }}</span>
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
                  Cancel
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
            <h2>Final Render</h2>
            <el-button
              native-type="button"
              type="primary"
              :loading="renderBusy"
              :disabled="renderBusy || !store.current?.completion.can_render"
              @click="createRender"
            >
              Export
            </el-button>
          </div>
          <div class="render-summary">
            <span>{{ store.current?.completion.completed_shots ?? 0 }}/{{ store.current?.completion.total_shots ?? 0 }} shots complete</span>
            <span>{{ Math.round(store.current?.completion.estimated_duration_seconds ?? 0) }}s estimated</span>
            <span v-if="store.current?.completion.render_disabled_reason">{{ store.current.completion.render_disabled_reason }}</span>
          </div>
          <div v-if="latestRender" class="render-card">
            <div class="task-main">
              <strong>Render #{{ latestRender.id }} v{{ latestRender.render_version }}</strong>
              <el-tag size="small" :type="latestRender.status === 'SUCCEEDED' ? 'success' : latestRender.status === 'FAILED' ? 'danger' : 'primary'">
                {{ latestRender.status }}
              </el-tag>
            </div>
            <div class="task-meta">
              <span>{{ latestRender.current_stage }}</span>
              <span>{{ Math.round(latestRender.progress * 100) }}%</span>
              <span v-if="latestRender.error_code">{{ latestRender.error_code }}: {{ latestRender.error_message }}</span>
            </div>
            <video v-if="latestRender.output_url" controls :src="latestRender.output_url" />
            <a v-if="latestRender.output_url" :href="latestRender.output_url" download>Download final video</a>
          </div>
        </div>
      </section>
    </section>
  </main>
</template>

<style scoped>
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
  .ops-panel,
  .settings-grid {
    grid-template-columns: 1fr;
  }
}
</style>
