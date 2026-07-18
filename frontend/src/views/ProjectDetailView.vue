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

import { api, type GenerationTask, type Shot, type ShotAssetSummary } from "@/api/client";
import { useProjectPolling } from "@/composables/useProjectPolling";
import { useStudioStore } from "@/stores/studio";

const route = useRoute();
const store = useStudioStore();
const { startPolling, tick } = useProjectPolling();
const draggedShotId = ref<number | null>(null);
const deletingShotId = ref<number | null>(null);
const actionBusy = ref(false);
const taskActionBusyId = ref<number | null>(null);
const expandedLogIds = ref<Set<number>>(new Set());
const projectId = computed(() => Number(route.params.id));
const selected = computed(() => store.selectedShot);
const videos = computed(() => (selected.value ? store.assetsByShot(selected.value.id, "VIDEO") : []));
const selectedTasks = computed(() => store.tasksForSelected);

onMounted(async () => {
  await store.loadProject(projectId.value);
  startPolling();
});

function statusType(status: Shot["status"]) {
  if (status.includes("APPROVED") || status === "COMPLETED") return "success";
  if (status.includes("REVIEW")) return "warning";
  if (status.includes("GENERATING")) return "primary";
  return "info";
}

function sourceLabel(asset: ShotAssetSummary | null) {
  if (!asset) return "当前不存在";
  if (asset.source_type === "inherited") {
    return `继承自 ${asset.source_shot_title ?? `Shot ${asset.source_shot_id ?? ""}`} 的实际尾帧`;
  }
  if (asset.source_type === "manual") return "手动指定";
  return "当前 Shot 生成";
}

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

async function deleteShot(shot: Shot, event: MouseEvent) {
  event.preventDefault();
  event.stopPropagation();
  try {
    await ElMessageBox.confirm(`确定删除 ${shot.title || `Shot ${shot.sort_order + 1}`}？`, "删除 Shot", {
      confirmButtonText: "删除",
      cancelButtonText: "取消",
      type: "warning",
    });
  } catch {
    return;
  }
  deletingShotId.value = shot.id;
  try {
    await store.deleteShot(shot.id);
    ElMessage.success("Shot 已删除");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "删除失败");
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
  if (task.status === "RESULT_READY" || task.status === "SUCCEEDED") return "success";
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
</script>

<template>
  <main class="workspace" v-loading="store.loading">
    <section class="workspace-header">
      <div>
        <h1>{{ store.current?.name }}</h1>
        <p>{{ store.current?.description || "Mock 后端阶段：所有生成资产和状态变化都会持久化。" }}</p>
      </div>
      <div class="header-actions">
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
          添加 Shot
        </el-button>
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
          <el-form label-position="top">
            <el-form-item label="标题">
              <el-input :model-value="selected.title" @change="store.updateSelectedShot({ title: String($event) })" />
            </el-form-item>
            <el-form-item label="描述">
              <el-input
                :model-value="selected.description"
                type="textarea"
                :rows="2"
                @change="store.updateSelectedShot({ description: String($event) })"
              />
            </el-form-item>
            <el-form-item label="时长">
              <el-input-number
                :model-value="selected.duration_seconds"
                :min="0.1"
                :max="60"
                @change="store.updateSelectedShot({ duration_seconds: Number($event) })"
              />
            </el-form-item>
            <el-form-item label="提示词">
              <el-input
                :model-value="selected.prompt"
                type="textarea"
                :rows="4"
                @change="store.updateSelectedShot({ prompt: String($event) })"
              />
            </el-form-item>
            <el-form-item label="负面约束">
              <el-input
                :model-value="selected.negative_prompt"
                type="textarea"
                :rows="3"
                @change="store.updateSelectedShot({ negative_prompt: String($event) })"
              />
            </el-form-item>
          </el-form>
        </div>

        <div class="asset-panel">
          <div class="panel-title">
            <h2>起始帧 Start Frame</h2>
          </div>
          <div class="asset-card">
            <el-image
              v-if="selected.start_frame"
              :src="selected.start_frame.url"
              :preview-src-list="[selected.start_frame.url]"
              fit="cover"
            >
              <template #error>
                <div class="asset-error">图片加载失败</div>
              </template>
            </el-image>
            <el-empty v-else description="当前不存在" />
            <dl>
              <dt>来源</dt>
              <dd>{{ sourceLabel(selected.start_frame) }}</dd>
              <dt>资产</dt>
              <dd>{{ selected.start_frame?.file_name ?? "无" }}</dd>
              <dt>ID</dt>
              <dd>{{ selected.start_frame?.asset_id ?? "无" }}</dd>
              <dt>时间</dt>
              <dd>{{ selected.start_frame?.created_at ?? "无" }}</dd>
            </dl>
          </div>
        </div>

        <div class="review-panel">
          <div class="panel-title">
            <h2>目标关键帧 Target Keyframe</h2>
            <el-button
              native-type="button"
              type="primary"
              :icon="Picture"
              :loading="actionBusy && selected.status === 'DRAFT'"
              :disabled="selected.status !== 'DRAFT' || actionBusy"
              @click="guarded(() => store.runAction(api.generateKeyframe), true)"
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
              批准
            </el-button>
            <el-button
              native-type="button"
              :icon="Close"
              :disabled="selected.status !== 'KEYFRAME_REVIEW' || actionBusy"
              @click="guarded(() => store.runAction(api.rejectKeyframe))"
            >
              拒绝
            </el-button>
          </div>
        </div>

        <div class="review-panel">
          <div class="panel-title">
            <h2>视频审核</h2>
            <el-button
              native-type="button"
              type="primary"
              :icon="VideoPlay"
              :loading="actionBusy && selected.status === 'KEYFRAME_APPROVED'"
              :disabled="selected.status !== 'KEYFRAME_APPROVED' || actionBusy"
              @click="guarded(() => store.runAction(api.generateVideo), true)"
            >
              生成视频
            </el-button>
          </div>
          <div class="asset-strip">
            <video v-for="asset in videos" :key="asset.id" controls :src="asset.url" />
            <el-empty v-if="!videos.length" description="暂无视频" />
          </div>
          <div class="button-row">
            <el-button
              native-type="button"
              type="success"
              :icon="Check"
              :disabled="selected.status !== 'VIDEO_REVIEW' || actionBusy"
              @click="guarded(() => store.runAction(api.approveVideo), true)"
            >
              批准并锁尾帧
            </el-button>
            <el-button
              native-type="button"
              :icon="Close"
              :disabled="selected.status !== 'VIDEO_REVIEW' || actionBusy"
              @click="guarded(() => store.runAction(api.rejectVideo))"
            >
              拒绝
            </el-button>
          </div>
        </div>

        <div class="asset-panel">
          <div class="panel-title">
            <h2>锁定尾帧 Locked Tail Frame</h2>
          </div>
          <div class="asset-card">
            <el-image
              v-if="selected.locked_tail_frame"
              :src="selected.locked_tail_frame.url"
              :preview-src-list="[selected.locked_tail_frame.url]"
              fit="cover"
            >
              <template #error>
                <div class="asset-error">尾帧加载失败</div>
              </template>
            </el-image>
            <el-empty v-else description="当前不存在" />
            <dl>
              <dt>来源</dt>
              <dd>{{ sourceLabel(selected.locked_tail_frame) }}</dd>
              <dt>资产</dt>
              <dd>{{ selected.locked_tail_frame?.file_name ?? "无" }}</dd>
            </dl>
          </div>
        </div>

        <div class="log-panel">
          <div class="panel-title">
            <h2>任务日志</h2>
            <el-button native-type="button" :icon="CaretRight" text @click="refreshProjectDetail">同步</el-button>
          </div>
          <div class="task-list">
            <div v-for="task in selectedTasks" :key="task.id" class="task-row">
              <div class="task-main">
                <strong>#{{ task.id }} {{ task.task_type }}</strong>
                <el-tag size="small" :type="taskType(task)">{{ task.status }}</el-tag>
              </div>
              <div class="task-meta">
                attempt {{ task.attempt_number }} / retries {{ task.retry_count }}/{{ task.max_attempts }}
                <span v-if="task.next_retry_at">next retry {{ task.next_retry_at }}</span>
                <span v-if="task.next_poll_at">next poll {{ task.next_poll_at }}</span>
                <span v-if="task.job_deadline_at">job deadline {{ task.job_deadline_at }}</span>
                <span v-if="task.cancellation_deadline_at">cancel deadline {{ task.cancellation_deadline_at }}</span>
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
                request: {{ log.request_id ?? "none" }} · shot: {{ log.shot_id ?? "none" }}
              </div>
            </el-timeline-item>
          </el-timeline>
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

.task-row {
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  padding: 10px;
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
</style>
