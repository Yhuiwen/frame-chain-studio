<script setup lang="ts">
import { Close, Refresh, RefreshRight } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";

import { api, type GenerationTask } from "@/api/client";
import { formatDateTime, statusLabel } from "@/constants/uiText";

const tasks = ref<GenerationTask[]>([]);
const loading = ref(false);
const busyTaskId = ref<number | null>(null);

const rows = computed(() =>
  tasks.value.map((task) => ({
    ...task,
    progress: Math.round(((task.remote_progress ?? task.processing_progress ?? 0) as number) * 100),
  })),
);

onMounted(loadTasks);

async function loadTasks() {
  loading.value = true;
  try {
    tasks.value = await api.listTasks();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "加载任务失败");
  } finally {
    loading.value = false;
  }
}

function idempotencyKey(action: string, taskId: number) {
  const randomPart = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `tasks:${action}:${taskId}:${randomPart}`;
}

function tagType(status: GenerationTask["status"]) {
  if (status === "FAILED") return "danger";
  if (status === "CANCELLED") return "info";
  if (status === "SUCCEEDED") return "success";
  if (status === "RETRY_WAIT" || status === "CANCELLING") return "warning";
  return "primary";
}

async function cancelTask(task: GenerationTask) {
  try {
    await ElMessageBox.confirm(`确认取消任务 #${task.id}？取消请求会被持久化并由工作进程处理。`, "取消任务", {
      confirmButtonText: "确认取消",
      cancelButtonText: "保留任务",
      type: "warning",
    });
  } catch {
    return;
  }
  busyTaskId.value = task.id;
  try {
    await api.cancelTask(task.id, "Cancelled from tasks page.", idempotencyKey("cancel", task.id));
    await loadTasks();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "取消任务失败");
  } finally {
    busyTaskId.value = null;
  }
}

async function retryTask(task: GenerationTask) {
  try {
    await ElMessageBox.confirm(`确认重试任务 #${task.id}？系统会创建一个新的关联任务尝试。`, "重试任务", {
      confirmButtonText: "确认重试",
      cancelButtonText: "返回",
      type: "warning",
    });
  } catch {
    return;
  }
  busyTaskId.value = task.id;
  try {
    await api.retryTask(task.id, "Manual retry from tasks page.", idempotencyKey("retry", task.id));
    await loadTasks();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "重试任务失败");
  } finally {
    busyTaskId.value = null;
  }
}
</script>

<template>
  <main class="tasks-page" v-loading="loading">
    <header class="page-header">
      <div>
        <h1>任务列表</h1>
        <RouterLink to="/">项目列表</RouterLink>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadTasks">刷新</el-button>
    </header>

    <el-table :data="rows" stripe>
      <el-table-column prop="id" label="任务 ID" width="90" />
      <el-table-column prop="provider_id" label="服务商" min-width="120" />
      <el-table-column label="项目" width="100">
        <template #default="{ row }">#{{ row.project_id }}</template>
      </el-table-column>
      <el-table-column label="镜头" width="90">
        <template #default="{ row }">#{{ row.shot_id }}</template>
      </el-table-column>
      <el-table-column label="任务类型" min-width="160"><template #default="{ row }">{{ statusLabel(row.task_type) }}</template></el-table-column>
      <el-table-column label="状态" width="150">
        <template #default="{ row }">
          <el-tag :type="tagType(row.status)" :title="row.status">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="进度" width="120">
        <template #default="{ row }">{{ row.progress }}%</template>
      </el-table-column>
      <el-table-column label="创建时间" min-width="180"><template #default="{ row }">{{ formatDateTime(row.created_at) }}</template></el-table-column>
      <el-table-column label="更新时间" min-width="180"><template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template></el-table-column>
      <el-table-column label="错误信息" min-width="220">
        <template #default="{ row }">{{ row.error_code }} {{ row.error_message }}</template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="row.can_cancel"
            size="small"
            :icon="Close"
            :loading="busyTaskId === row.id"
            @click="cancelTask(row)"
          >
            取消任务
          </el-button>
          <el-button
            v-if="row.can_retry"
            size="small"
            type="primary"
            :icon="RefreshRight"
            :loading="busyTaskId === row.id"
            @click="retryTask(row)"
          >
            重试
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </main>
</template>

<style scoped>
.tasks-page {
  padding: 24px;
}

.page-header {
  align-items: center;
  display: flex;
  justify-content: space-between;
  margin-bottom: 18px;
}

.page-header h1 {
  margin: 0 0 6px;
}
</style>
