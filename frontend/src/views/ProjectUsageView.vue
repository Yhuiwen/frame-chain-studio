<script setup lang="ts">
import { Download, Refresh } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { computed, onMounted, ref } from "vue";
import { RouterLink, useRoute } from "vue-router";

import { api, type GenerationUsageRecord, type ProjectBudgetPolicy, type UsageSummary } from "@/api/client";
import { statusLabel } from "@/constants/uiText";

const route = useRoute();
const projectId = computed(() => Number(route.params.projectId));
const summary = ref<UsageSummary | null>(null);
const records = ref<GenerationUsageRecord[]>([]);
const budget = ref<ProjectBudgetPolicy | null>(null);
const loading = ref(false);
const saving = ref(false);
const budgetForm = ref({
  enabled: false,
  currency: "USD",
  warning_limit: "",
  hard_limit: "",
  per_request_limit: "",
  unknown_cost_policy: "ALLOW_WITH_WARNING" as ProjectBudgetPolicy["unknown_cost_policy"],
});

onMounted(loadUsage);

async function loadUsage() {
  loading.value = true;
  try {
    const [summaryResult, recordsResult, budgetResult] = await Promise.all([
      api.getProjectUsageSummary(projectId.value),
      api.listProjectUsageRecords(projectId.value),
      api.getProjectBudget(projectId.value),
    ]);
    summary.value = summaryResult;
    records.value = recordsResult;
    budget.value = budgetResult;
    budgetForm.value = {
      enabled: budgetResult.enabled,
      currency: budgetResult.currency,
      warning_limit: budgetResult.warning_limit ?? "",
      hard_limit: budgetResult.hard_limit ?? "",
      per_request_limit: budgetResult.per_request_limit ?? "",
      unknown_cost_policy: budgetResult.unknown_cost_policy,
    };
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Failed to load usage");
  } finally {
    loading.value = false;
  }
}

async function saveBudget() {
  saving.value = true;
  try {
    budget.value = await api.updateProjectBudget(projectId.value, {
      enabled: budgetForm.value.enabled,
      currency: budgetForm.value.currency,
      warning_limit: budgetForm.value.warning_limit || null,
      hard_limit: budgetForm.value.hard_limit || null,
      per_request_limit: budgetForm.value.per_request_limit || null,
      unknown_cost_policy: budgetForm.value.unknown_cost_policy,
      period_type: "PROJECT_TOTAL",
    });
    ElMessage.success("Budget policy saved");
    await loadUsage();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Save budget failed");
  } finally {
    saving.value = false;
  }
}

function displayCost(value: string | null, currency: string) {
  return value === null ? "UNKNOWN" : `${value} ${currency}`;
}

function statusTag(status: GenerationUsageRecord["status"]) {
  if (status === "ACTUAL") return "success";
  if (status === "UNKNOWN") return "warning";
  if (status === "WAIVED") return "info";
  return "primary";
}
</script>

<template>
  <main class="usage-page" v-loading="loading">
    <header class="page-header">
      <div>
        <h1>用量与预算</h1>
        <RouterLink :to="`/projects/${projectId}`">返回项目</RouterLink>
      </div>
      <div class="actions">
        <el-button :icon="Download" tag="a" :href="api.usageCsvUrl(projectId)">导出 CSV</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="loadUsage">刷新</el-button>
      </div>
    </header>

    <section class="summary-grid">
      <div class="metric" v-for="item in summary?.currencies ?? []" :key="item.currency">
        <span>{{ item.currency }}</span>
        <strong>{{ item.actual_total }}</strong>
        <small>预估 {{ item.estimated_total }}</small>
      </div>
      <div class="metric">
        <span>生成请求</span>
        <strong>{{ summary?.request_count ?? 0 }}</strong>
        <small>{{ summary?.image_request_count ?? 0 }} image · {{ summary?.video_request_count ?? 0 }} video</small>
      </div>
      <div class="metric">
        <span>费用未知</span>
        <strong>{{ summary?.unknown_cost_count ?? 0 }}</strong>
        <small>保持“未知”状态，不会按零费用处理</small>
      </div>
    </section>

    <section class="budget-panel">
      <header class="panel-header">
        <h2>预算策略</h2>
        <el-button type="primary" :loading="saving" @click="saveBudget">保存预算</el-button>
      </header>
      <el-form label-position="top" class="budget-form">
        <el-form-item label="启用"><el-switch v-model="budgetForm.enabled" /></el-form-item>
        <el-form-item label="币种"><el-input v-model="budgetForm.currency" /></el-form-item>
        <el-form-item label="警告额度"><el-input v-model="budgetForm.warning_limit" /></el-form-item>
        <el-form-item label="硬性额度"><el-input v-model="budgetForm.hard_limit" /></el-form-item>
        <el-form-item label="单次请求额度"><el-input v-model="budgetForm.per_request_limit" /></el-form-item>
        <el-form-item label="未知费用策略">
          <el-select v-model="budgetForm.unknown_cost_policy">
            <el-option label="允许并警告" value="ALLOW_WITH_WARNING" />
            <el-option label="阻止" value="BLOCK" />
          </el-select>
        </el-form-item>
      </el-form>
    </section>

    <el-table :data="records" stripe>
      <el-table-column prop="created_at" label="创建时间" min-width="180" />
      <el-table-column label="请求" width="110">
        <template #default="{ row }">#{{ row.generation_request_id ?? "-" }}</template>
      </el-table-column>
      <el-table-column label="任务" width="100">
        <template #default="{ row }">#{{ row.generation_task_id ?? "-" }}</template>
      </el-table-column>
      <el-table-column prop="record_type" label="类型" min-width="150" />
      <el-table-column label="状态" width="130">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status)" :title="row.status">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="预估费用" min-width="150">
        <template #default="{ row }">{{ displayCost(row.estimated_cost, row.currency) }}</template>
      </el-table-column>
      <el-table-column label="实际费用" min-width="150">
        <template #default="{ row }">{{ displayCost(row.actual_cost, row.currency) }}</template>
      </el-table-column>
      <el-table-column prop="cost_source" label="费用来源" min-width="150" />
    </el-table>
  </main>
</template>

<style scoped>
.usage-page {
  padding: 24px;
}

.page-header,
.panel-header,
.actions {
  align-items: center;
  display: flex;
  gap: 12px;
  justify-content: space-between;
}

.page-header {
  margin-bottom: 18px;
}

.page-header h1,
.panel-header h2 {
  margin: 0 0 6px;
}

.summary-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-bottom: 20px;
}

.metric {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  display: grid;
  gap: 4px;
  padding: 14px;
}

.metric span,
.metric small {
  color: #64748b;
}

.metric strong {
  font-size: 24px;
}

.budget-panel {
  border-top: 1px solid #e5e7eb;
  margin-bottom: 20px;
  padding-top: 18px;
}

.budget-form {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(6, minmax(0, 1fr));
}

@media (max-width: 900px) {
  .summary-grid,
  .budget-form {
    grid-template-columns: 1fr;
  }
}
</style>
