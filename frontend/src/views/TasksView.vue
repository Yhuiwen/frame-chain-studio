<script setup lang="ts">
import { Close, Refresh, RefreshRight } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";

import { api, type GenerationTask } from "@/api/client";

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
    ElMessage.error(error instanceof Error ? error.message : "Failed to load tasks");
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
    await ElMessageBox.confirm(`Cancel task #${task.id}?`, "Cancel Task", {
      confirmButtonText: "Cancel",
      cancelButtonText: "Keep",
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
    ElMessage.error(error instanceof Error ? error.message : "Cancel failed");
  } finally {
    busyTaskId.value = null;
  }
}

async function retryTask(task: GenerationTask) {
  busyTaskId.value = task.id;
  try {
    await api.retryTask(task.id, "Manual retry from tasks page.", idempotencyKey("retry", task.id));
    await loadTasks();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Retry failed");
  } finally {
    busyTaskId.value = null;
  }
}
</script>

<template>
  <main class="tasks-page" v-loading="loading">
    <header class="page-header">
      <div>
        <h1>Tasks</h1>
        <RouterLink to="/">Projects</RouterLink>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadTasks">Refresh</el-button>
    </header>

    <el-table :data="rows" stripe>
      <el-table-column prop="id" label="Task" width="90" />
      <el-table-column prop="provider_id" label="Provider" min-width="120" />
      <el-table-column label="Project" width="100">
        <template #default="{ row }">#{{ row.project_id }}</template>
      </el-table-column>
      <el-table-column label="Shot" width="90">
        <template #default="{ row }">#{{ row.shot_id }}</template>
      </el-table-column>
      <el-table-column prop="task_type" label="Type" min-width="160" />
      <el-table-column label="Status" width="150">
        <template #default="{ row }">
          <el-tag :type="tagType(row.status)">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="Progress" width="120">
        <template #default="{ row }">{{ row.progress }}%</template>
      </el-table-column>
      <el-table-column prop="created_at" label="Created" min-width="180" />
      <el-table-column prop="updated_at" label="Updated" min-width="180" />
      <el-table-column label="Error" min-width="220">
        <template #default="{ row }">{{ row.error_code }} {{ row.error_message }}</template>
      </el-table-column>
      <el-table-column label="Actions" width="180" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="row.can_cancel"
            size="small"
            :icon="Close"
            :loading="busyTaskId === row.id"
            @click="cancelTask(row)"
          >
            Cancel
          </el-button>
          <el-button
            v-if="row.can_retry"
            size="small"
            type="primary"
            :icon="RefreshRight"
            :loading="busyTaskId === row.id"
            @click="retryTask(row)"
          >
            Retry
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
