<script setup lang="ts">
import { Check, CircleClose, Plus, Refresh, VideoCamera } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";

import {
  api,
  type ProviderAdapterType,
  type ProviderModelGenerationType,
  type ProviderModelProfile,
  type ProviderProfile,
  type ToApisGateState,
} from "@/api/client";

const profiles = ref<ProviderProfile[]>([]);
const models = ref<ProviderModelProfile[]>([]);
const selectedId = ref<number | null>(null);
const loading = ref(false);
const busy = ref(false);
const toapisGate = ref<ToApisGateState | null>(null);
const profileForm = ref({
  name: "",
  provider_key: "",
  adapter_type: "MAPPED_ASYNC_HTTP" as ProviderAdapterType,
  display_name: "",
  description: "",
  base_url: "",
  secret_env_var: "",
  enabled: true,
  config: "{}",
});
const modelForm = ref({
  model_key: "",
  remote_model: "",
  display_name: "",
  generation_type: "IMAGE" as ProviderModelGenerationType,
  enabled: true,
  capabilities: "{}",
  limits: "{}",
  pricing: "{\"rules\":[{\"unit\":\"REQUEST\",\"price\":\"0\"}]}",
  currency: "USD",
});

const selectedProfile = computed(() => profiles.value.find((item) => item.id === selectedId.value) ?? null);

onMounted(loadProfiles);

async function loadProfiles() {
  loading.value = true;
  try {
    profiles.value = await api.listProviderProfiles();
    if (profiles.value.some((item) => item.provider_key === "toapis")) toapisGate.value = await api.getToApisGate();
    if (!selectedId.value && profiles.value.length > 0) selectedId.value = profiles.value[0].id;
    if (selectedId.value) await loadModels(selectedId.value);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Failed to load provider settings");
  } finally {
    loading.value = false;
  }
}

async function runToApisAction(action: "review" | "preflight" | "balance" | "enable" | "disable") {
  busy.value = true;
  try {
    if (action === "review") toapisGate.value = await api.reviewToApisPricing();
    if (action === "preflight") { await api.preflightToApis(); toapisGate.value = await api.getToApisGate(); }
    if (action === "balance") toapisGate.value = await api.confirmToApisBalance();
    if (action === "enable") {
      if (!toapisGate.value?.pricing_snapshot_hash) throw new Error("Review pricing first");
      toapisGate.value = await api.enableToApisLive(toapisGate.value.pricing_snapshot_hash);
    }
    if (action === "disable") toapisGate.value = await api.disableToApisLive();
    await loadProfiles();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "TOAPIS gate operation failed");
  } finally { busy.value = false; }
}

async function loadModels(providerId: number) {
  selectedId.value = providerId;
  models.value = await api.listProviderModels(providerId);
}

function parseJson(value: string, label: string) {
  try {
    const parsed = JSON.parse(value || "{}") as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
    return parsed as Record<string, unknown>;
  } catch {
    throw new Error(`${label} must be a JSON object`);
  }
}

async function createProfile() {
  busy.value = true;
  try {
    const created = await api.createProviderProfile({
      ...profileForm.value,
      display_name: profileForm.value.display_name || profileForm.value.name,
      config: parseJson(profileForm.value.config, "Config"),
    });
    ElMessage.success("Provider profile created");
    selectedId.value = created.id;
    await loadProfiles();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Create provider failed");
  } finally {
    busy.value = false;
  }
}

async function createModel() {
  if (!selectedId.value) return;
  busy.value = true;
  try {
    await api.createProviderModel(selectedId.value, {
      ...modelForm.value,
      display_name: modelForm.value.display_name || modelForm.value.model_key,
      capabilities: parseJson(modelForm.value.capabilities, "Capabilities"),
      limits: parseJson(modelForm.value.limits, "Limits"),
      pricing: parseJson(modelForm.value.pricing, "Pricing"),
    });
    ElMessage.success("Model profile added");
    await loadModels(selectedId.value);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Create model failed");
  } finally {
    busy.value = false;
  }
}

async function validateProfile(profile: ProviderProfile) {
  busy.value = true;
  try {
    const result = await api.validateProviderProfile(profile.id);
    if (result.errors.length > 0) ElMessage.error(result.errors.join(", "));
    else ElMessage.success(result.warnings.length > 0 ? result.warnings.join(", ") : "Provider profile is valid");
    await loadProfiles();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Validation failed");
  } finally {
    busy.value = false;
  }
}

async function verifyContract(profile: ProviderProfile) {
  busy.value = true;
  try {
    const result = await api.verifyProviderContract(profile.id);
    ElMessage.success(`Contract verification ${result.status}`);
    await loadProfiles();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Contract verification failed");
  } finally {
    busy.value = false;
  }
}

async function verifyLive(profile: ProviderProfile) {
  busy.value = true;
  try {
    const result = await api.verifyProviderLive(profile.id, { confirm_live: false, max_cost: null });
    ElMessage.warning(result.error_code ?? result.status);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Live verification failed");
  } finally {
    busy.value = false;
  }
}

async function archiveProfile(profile: ProviderProfile) {
  try {
    await ElMessageBox.confirm(`Archive ${profile.display_name || profile.name}?`, "Archive Provider", {
      confirmButtonText: "Archive",
      cancelButtonText: "Cancel",
      type: "warning",
    });
  } catch {
    return;
  }
  await api.archiveProviderProfile(profile.id);
  ElMessage.success("Provider archived");
  selectedId.value = null;
  await loadProfiles();
}
</script>

<template>
  <main class="settings-page" v-loading="loading">
    <header class="page-header">
      <div>
        <h1>Provider Settings</h1>
        <RouterLink to="/">Projects</RouterLink>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadProfiles">Refresh</el-button>
    </header>

    <section class="layout">
      <aside class="sidebar">
        <el-button type="primary" :icon="Plus" :loading="busy" @click="createProfile">Create Provider</el-button>
        <el-form label-position="top" class="form">
          <el-form-item label="Name"><el-input v-model="profileForm.name" /></el-form-item>
          <el-form-item label="Provider Key"><el-input v-model="profileForm.provider_key" /></el-form-item>
          <el-form-item label="Adapter">
            <el-select v-model="profileForm.adapter_type">
              <el-option label="Mapped HTTP" value="MAPPED_ASYNC_HTTP" />
              <el-option label="TOAPIS" value="TOAPIS" />
              <el-option label="Fake" value="FAKE" />
            </el-select>
          </el-form-item>
          <el-form-item label="Base URL"><el-input v-model="profileForm.base_url" /></el-form-item>
          <el-form-item label="Secret Env Var"><el-input v-model="profileForm.secret_env_var" /></el-form-item>
          <el-form-item label="Config JSON"><el-input v-model="profileForm.config" type="textarea" :rows="4" /></el-form-item>
          <el-checkbox v-model="profileForm.enabled">Enabled</el-checkbox>
        </el-form>
      </aside>

      <section class="content">
        <el-alert
          v-if="selectedProfile?.adapter_type === 'TOAPIS'"
          type="info"
          :closable="false"
          title="Set TOAPIS_API_KEY before starting Frame Chain Studio. The application never stores or displays the API key."
          description="TOAPIS · https://toapis.com/v1 · Seedream 5.0 (2K) · Vidu Q3 Pro (720p, audio off, two ordered anchors). Remote cancellation and live verification remain unverified."
        />
        <el-card v-if="selectedProfile?.adapter_type === 'TOAPIS' && toapisGate" class="models-panel">
          <template #header><strong>TOAPIS Live Gate</strong></template>
          <p>Pricing: 6.3 credits/image request; 20 credits/video second · {{ toapisGate.billing_unit }} · {{ toapisGate.pricing_version }}</p>
          <p>Two-shot estimate: 2 × 6.3 + 8 × 20 = {{ toapisGate.estimated_two_shot_billing_units }} credits; recommended ceiling {{ toapisGate.recommended_test_ceiling }}.</p>
          <p>Pricing reviewed: {{ toapisGate.pricing_reviewed ? "Yes" : "Needs review" }} · Models: {{ toapisGate.preflight.image_model_accessible && toapisGate.preflight.video_model_accessible ? "Accessible" : "Not verified" }} · Balance confirmed: {{ toapisGate.account_balance_sufficient ? "Yes" : "No" }} · Live: {{ toapisGate.live_orchestration_enabled ? "Enabled" : "Disabled" }}</p>
          <el-alert type="warning" :closable="false" title="TOAPIS model credits, token remain_quota, and USD are different units; Frame Chain Studio does not convert between them." />
          <div class="gate-actions">
            <el-button :loading="busy" @click="runToApisAction('review')">Review Pricing</el-button>
            <el-button :loading="busy" @click="runToApisAction('preflight')">Run Model Preflight</el-button>
            <el-button :loading="busy" @click="runToApisAction('balance')">Confirm Account Capacity</el-button>
            <el-button type="primary" :loading="busy" @click="runToApisAction('enable')">Enable Live</el-button>
            <el-button type="danger" :loading="busy" @click="runToApisAction('disable')">Disable Live</el-button>
          </div>
        </el-card>
        <el-table :data="profiles" highlight-current-row @current-change="(row: ProviderProfile | null) => row && loadModels(row.id)">
          <el-table-column prop="provider_key" label="Provider" min-width="150" />
          <el-table-column prop="display_name" label="Display" min-width="150" />
          <el-table-column prop="adapter_type" label="Adapter" width="150" />
          <el-table-column label="Configured" width="120">
            <template #default="{ row }">
              <el-tag :type="row.secret_configured || row.adapter_type === 'FAKE' ? 'success' : 'warning'">
                {{ row.secret_configured || row.adapter_type === "FAKE" ? "Ready" : "Missing" }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="Status" width="180">
            <template #default="{ row }">
              <el-tag :type="row.contract_verified ? 'success' : 'info'">Contract {{ row.contract_verified ? "OK" : "Open" }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="Actions" width="360" fixed="right">
            <template #default="{ row }">
              <el-button size="small" :icon="Check" :loading="busy" @click="validateProfile(row)">Validate</el-button>
              <el-button size="small" :icon="Check" :loading="busy" @click="verifyContract(row)">Contract</el-button>
              <el-button size="small" :icon="VideoCamera" :loading="busy" @click="verifyLive(row)">Live</el-button>
              <el-button size="small" :icon="CircleClose" @click="archiveProfile(row)">Archive</el-button>
            </template>
          </el-table-column>
        </el-table>

        <section v-if="selectedProfile" class="models-panel">
          <header class="panel-header">
            <h2>{{ selectedProfile.display_name || selectedProfile.name }} Models</h2>
            <el-button type="primary" :icon="Plus" :loading="busy" @click="createModel">Add Model</el-button>
          </header>
          <el-form label-position="top" class="model-form">
            <el-form-item label="Model Key"><el-input v-model="modelForm.model_key" /></el-form-item>
            <el-form-item label="Remote Model"><el-input v-model="modelForm.remote_model" /></el-form-item>
            <el-form-item label="Type">
              <el-select v-model="modelForm.generation_type">
                <el-option label="Image" value="IMAGE" />
                <el-option label="Video" value="VIDEO" />
              </el-select>
            </el-form-item>
            <el-form-item label="Currency"><el-input v-model="modelForm.currency" /></el-form-item>
            <el-form-item label="Pricing JSON"><el-input v-model="modelForm.pricing" type="textarea" :rows="3" /></el-form-item>
          </el-form>
          <el-table :data="models" stripe>
            <el-table-column prop="model_key" label="Model" min-width="160" />
            <el-table-column prop="remote_model" label="Remote Model" min-width="180" />
            <el-table-column prop="generation_type" label="Type" width="110" />
            <el-table-column prop="currency" label="Currency" width="110" />
            <el-table-column label="Pricing" min-width="240">
              <template #default="{ row }">{{ JSON.stringify(row.pricing) }}</template>
            </el-table-column>
          </el-table>
        </section>
      </section>
    </section>
  </main>
</template>

<style scoped>
.settings-page {
  padding: 24px;
}

.page-header,
.panel-header {
  align-items: center;
  display: flex;
  justify-content: space-between;
  margin-bottom: 18px;
}

.page-header h1,
.panel-header h2 {
  margin: 0 0 6px;
}

.layout {
  display: grid;
  gap: 18px;
  grid-template-columns: minmax(280px, 340px) 1fr;
}

.sidebar {
  border-right: 1px solid #e5e7eb;
  padding-right: 18px;
}

.form,
.model-form {
  margin-top: 16px;
}

.models-panel {
  margin-top: 24px;
}

.model-form {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

@media (max-width: 900px) {
  .layout,
  .model-form {
    grid-template-columns: 1fr;
  }

  .sidebar {
    border-right: 0;
    padding-right: 0;
  }
}
</style>
