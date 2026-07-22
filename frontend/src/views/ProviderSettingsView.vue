<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus";
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import {
  api,
  type ProviderModelProfile,
  type ProviderProfile,
} from "@/api/client";
import { useStudioStore } from "@/stores/studio";

const route = useRoute();
const router = useRouter();
const store = useStudioStore();
const profiles = ref<ProviderProfile[]>([]);
const models = ref<Record<number, ProviderModelProfile[]>>({});
const loading = ref(false);
const busy = ref(false);
const json = ref("");
const parseError = ref("");
const projectId = computed(() =>
  route.name === "project-provider-settings"
    ? Number(route.params.projectId)
    : null,
);
const contextual = computed(() => projectId.value !== null);
const project = computed(() => (contextual.value ? store.current : null));
const templates: Record<string, object> = {
  fake: {
    display_name: "模拟 HTTP 服务商",
    provider_key: "fake-http",
    adapter: "FAKE",
    base_url: "http://127.0.0.1:8091/fake/v1",
    secret_env: "",
    models: [
      {
        model_key: "fake-image",
        remote_model: "fake-image",
        display_name: "模拟图片模型",
        type: "IMAGE",
        enabled: true,
      },
      {
        model_key: "fake-video",
        remote_model: "fake-video",
        display_name: "模拟视频模型",
        type: "VIDEO",
        enabled: true,
      },
    ],
  },
  toapis: {
    display_name: "TOAPIS",
    provider_key: "toapis",
    adapter: "TOAPIS",
    base_url: "https://toapis.com/v1",
    secret_env: "TOAPIS_API_KEY",
    models: [
      {
        model_key: "seedream-5",
        remote_model: "doubao-seedream-5-0",
        display_name: "Seedream 5.0",
        type: "IMAGE",
        enabled: true,
      },
      {
        model_key: "vidu-q3-pro",
        remote_model: "viduq3-pro",
        display_name: "Vidu Q3 Pro",
        type: "VIDEO",
        enabled: true,
      },
    ],
  },
  custom: {
    display_name: "自定义兼容服务商",
    provider_key: "custom",
    adapter: "MAPPED_ASYNC_HTTP",
    base_url: "https://example.invalid/v1",
    secret_env: "CUSTOM_PROVIDER_API_KEY",
    models: [],
  },
};
const preview = computed(() => {
  try {
    const value = JSON.parse(json.value);
    parseError.value = "";
    return value as Record<string, unknown>;
  } catch {
    parseError.value = json.value.trim() ? "JSON 格式不正确。" : "";
    return null;
  }
});

onMounted(async () => {
  if (
    contextual.value &&
    (!Number.isInteger(projectId.value) || Number(projectId.value) <= 0)
  ) {
    await router.replace("/404");
    return;
  }
  loading.value = true;
  try {
    await loadProfiles();
  } catch {
    if (contextual.value) await router.replace("/404");
    else ElMessage.error("服务商配置加载失败");
  } finally {
    loading.value = false;
  }
});

async function loadProfiles() {
  profiles.value = await api.listProviderProfiles();
  await Promise.all(
    profiles.value.map(async (profile) => {
      models.value[profile.id] = await api.listProviderModels(profile.id);
    }),
  );
}
async function refresh() {
  loading.value = true;
  try {
    await loadProfiles();
  } finally {
    loading.value = false;
  }
}
function useTemplate(key: string) {
  json.value = JSON.stringify(templates[key], null, 2);
}
async function importConfig() {
  if (!preview.value) return;
  busy.value = true;
  try {
    await api.importProviderConfig(preview.value);
    ElMessage.success("服务商配置已导入");
    json.value = "";
    await loadProfiles();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "导入失败");
  } finally {
    busy.value = false;
  }
}
async function toggle(profile: ProviderProfile) {
  await api.updateProviderProfile(profile.id, { enabled: !profile.enabled });
  await loadProfiles();
}
async function syncModels(profile: ProviderProfile) {
  busy.value = true;
  try {
    const result = await api.syncProviderModels(profile.id, { confirm: false });
    if (!result.supported) {
      ElMessage.warning(result.message);
      return;
    }
    const names = result.models
      .map(
        (model) =>
          `${model.display_name}（${model.type === "IMAGE" ? "图片" : "视频"}）`,
      )
      .join("、");
    await ElMessageBox.confirm(
      `${result.message}\n${names}\n新模型默认停用。`,
      `同步 ${profile.display_name || profile.name} 模型`,
      { confirmButtonText: "确认保存", cancelButtonText: "取消" },
    );
    await api.syncProviderModels(profile.id, {
      confirm: true,
      models: result.models,
    });
    ElMessage.success("模型同步结果已保存");
    await loadProfiles();
  } catch (error) {
    if (error !== "cancel")
      ElMessage.error(error instanceof Error ? error.message : "同步失败");
  } finally {
    busy.value = false;
  }
}
async function removeProvider(profile: ProviderProfile) {
  try {
    await ElMessageBox.confirm(
      "删除前会检查项目引用、活动任务和模型引用；历史任务与资产不会被删除。",
      "删除服务商配置",
      {
        type: "warning",
        confirmButtonText: "删除配置",
        cancelButtonText: "取消",
      },
    );
    await api.deleteProviderConfig(profile.id);
    ElMessage.success("服务商配置已删除");
    await loadProfiles();
  } catch (error) {
    if (error !== "cancel")
      ElMessage.error(error instanceof Error ? error.message : "删除失败");
  }
}
function count(profile: ProviderProfile, type: "IMAGE" | "VIDEO") {
  return (models.value[profile.id] ?? []).filter(
    (model) => model.generation_type === type,
  ).length;
}
function currentUses(profile: ProviderProfile) {
  const uses = [];
  if (project.value?.image_provider_id === profile.provider_key)
    uses.push("图片当前使用");
  if (project.value?.video_provider_id === profile.provider_key)
    uses.push("视频当前使用");
  return uses;
}
function modelSelected(profile: ProviderProfile, model: ProviderModelProfile) {
  return (
    (model.generation_type === "IMAGE" &&
      project.value?.image_provider_id === profile.provider_key &&
      project.value.image_model === model.model_key) ||
    (model.generation_type === "VIDEO" &&
      project.value?.video_provider_id === profile.provider_key &&
      project.value.video_model === model.model_key)
  );
}
</script>

<template>
  <main
    :class="contextual ? 'workspace-page' : 'page'"
    :data-testid="contextual ? 'workspace-page-providers' : undefined"
    v-loading="loading"
  >
    <Teleport
      v-if="contextual"
      key="provider-settings-actions"
      to="#project-workspace-actions"
      ><el-button
        @click="
          router.push({ name: 'project-workbench', params: { projectId } })
        "
        >返回项目工作台</el-button
      ><el-button @click="refresh">刷新</el-button></Teleport
    >
    <section class="provider-content">
      <header v-if="!contextual">
        <div>
          <h1>服务商设置</h1>
          <p>管理可用于图片和视频生成的服务商与模型。</p>
        </div>
        <RouterLink to="/">返回项目列表</RouterLink>
      </header>
      <p v-else class="context-note">
        这里管理全局服务商配置，并标出当前项目正在使用的服务商和模型。
      </p>
      <el-card class="import-card"
        ><template #header><strong>导入服务商配置</strong></template>
        <div class="templates">
          <span>使用内置模板：</span
          ><el-button @click="useTemplate('fake')">模拟服务商</el-button
          ><el-button @click="useTemplate('toapis')">TOAPIS</el-button
          ><el-button @click="useTemplate('custom')"
            >自定义兼容服务商</el-button
          >
        </div>
        <el-input
          v-model="json"
          type="textarea"
          :rows="7"
          placeholder="粘贴 JSON 配置；只能填写 secret_env 名称，不能包含真实密钥。"
        />
        <p v-if="parseError" class="error">{{ parseError }}</p>
        <div v-if="preview" class="summary">
          <strong>{{ preview.display_name }}</strong
          ><span>服务商标识：{{ preview.provider_key }}</span
          ><span
            >将导入
            {{ Array.isArray(preview.models) ? preview.models.length : 0 }}
            个模型</span
          >
        </div>
        <el-button
          type="primary"
          :disabled="!preview"
          :loading="busy"
          @click="importConfig"
          >确认导入</el-button
        ></el-card
      >
      <h2>已配置服务商</h2>
      <section class="cards">
        <el-card
          v-for="profile in profiles"
          :key="profile.id"
          class="provider-card"
          ><template #header
            ><div class="title">
              <div>
                <strong>{{ profile.display_name || profile.name }}</strong>
                <div class="use-tags">
                  <el-tag
                    v-for="usage in currentUses(profile)"
                    :key="usage"
                    type="primary"
                    size="small"
                    >{{ usage }}</el-tag
                  >
                </div>
              </div>
              <el-tag :type="profile.enabled ? 'success' : 'info'">{{
                profile.enabled ? "已启用" : "已停用"
              }}</el-tag>
            </div></template
          >
          <dl>
            <dt>类型</dt>
            <dd>{{ profile.adapter_type }}</dd>
            <dt>图片模型</dt>
            <dd>{{ count(profile, "IMAGE") }}</dd>
            <dt>视频模型</dt>
            <dd>{{ count(profile, "VIDEO") }}</dd>
            <dt>密钥</dt>
            <dd>
              {{
                profile.adapter_type === "FAKE"
                  ? "无需密钥"
                  : profile.secret_configured
                    ? "已配置"
                    : "未配置"
              }}
            </dd>
          </dl>
          <el-collapse
            ><el-collapse-item title="模型"
              ><div
                v-for="model in models[profile.id]"
                :key="model.id"
                class="model-row"
              >
                <span
                  >{{ model.display_name }} ·
                  {{
                    model.generation_type === "IMAGE" ? "图片" : "视频"
                  }}</span
                ><el-tag
                  v-if="modelSelected(profile, model)"
                  size="small"
                  type="primary"
                  >当前选择</el-tag
                ><el-tag
                  v-else
                  size="small"
                  :type="model.enabled ? 'success' : 'info'"
                  >{{ model.enabled ? "可用" : "停用" }}</el-tag
                >
              </div></el-collapse-item
            ><el-collapse-item title="高级诊断"
              ><p>服务商标识：{{ profile.provider_key }}</p>
              <p>适配器：{{ profile.adapter_type }}</p>
              <p>基础 URL：{{ profile.base_url }}</p>
              <p>配置版本：{{ profile.config_revision }}</p></el-collapse-item
            ></el-collapse
          >
          <div class="actions">
            <el-button :loading="busy" @click="syncModels(profile)"
              >同步模型</el-button
            ><el-dropdown
              ><el-button>更多操作</el-button
              ><template #dropdown
                ><el-dropdown-menu
                  ><el-dropdown-item @click="toggle(profile)">{{
                    profile.enabled ? "停用" : "启用"
                  }}</el-dropdown-item
                  ><el-dropdown-item divided @click="removeProvider(profile)"
                    >删除配置</el-dropdown-item
                  ></el-dropdown-menu
                ></template
              ></el-dropdown
            >
          </div></el-card
        >
      </section>
    </section>
  </main>
</template>

<style scoped>
.page {
  min-height: 100vh;
  padding: clamp(16px, 3vw, 36px);
}
.provider-content {
  width: 100%;
  min-width: 0;
}
header,
.title,
.templates,
.summary,
.actions,
.model-row,
.use-tags {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.context-note {
  margin: 0 0 18px;
  color: var(--muted);
}
.import-card {
  margin: 0 0 24px;
}
.templates,
.actions {
  justify-content: flex-start;
  margin-bottom: 12px;
}
.summary {
  justify-content: flex-start;
  padding: 12px 0;
  color: var(--el-text-color-secondary);
}
.error {
  color: var(--el-color-danger);
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;
}
.provider-card {
  min-width: 0;
}
.use-tags {
  justify-content: flex-start;
  margin-top: 7px;
}
dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 8px;
}
dd {
  margin: 0;
  text-align: right;
}
.model-row {
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
}
@media (max-width: 600px) {
  .provider-content {
    padding: 14px;
  }
}
</style>
