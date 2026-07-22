<script setup lang="ts">
import { Delete, Edit, Picture, Plus, Refresh } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import {
  api,
  type Character,
  type Location,
  type StyleProfile,
} from "@/api/client";

const route = useRoute();
const projectId = computed(() => Number(route.params.projectId));
const loading = ref(false);
const busy = ref(false);
const activeTab = ref("characters");
const dialogVisible = ref(false);
const characters = ref<Character[]>([]);
const locations = ref<Location[]>([]);
const styles = ref<StyleProfile[]>([]);
const characterFile = ref<File | null>(null);
const previewUrl = ref("");
const characterForm = reactive({ name: "", description: "", appearance: "" });
onMounted(loadLibrary);
async function loadLibrary() {
  loading.value = true;
  try {
    [characters.value, locations.value, styles.value] = await Promise.all([
      api.listCharacters(projectId.value),
      api.listLocations(projectId.value),
      api.listStyleProfiles(projectId.value),
    ]);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "资料库加载失败");
  } finally {
    loading.value = false;
  }
}
function openCharacterDialog() {
  Object.assign(characterForm, { name: "", description: "", appearance: "" });
  characterFile.value = null;
  previewUrl.value = "";
  dialogVisible.value = true;
}
function selectImage(file: { raw: File }) {
  characterFile.value = file.raw;
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value);
  previewUrl.value = URL.createObjectURL(file.raw);
}
async function createCharacter() {
  if (!characterFile.value || !characterForm.name.trim()) return;
  busy.value = true;
  try {
    await api.createCharacterFromImage(projectId.value, characterFile.value, {
      ...characterForm,
    });
    ElMessage.success("角色已创建并绑定主参考图。");
    dialogVisible.value = false;
    await loadLibrary();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "角色创建失败");
  } finally {
    busy.value = false;
  }
}
async function editCharacter(item: Character) {
  try {
    const result = await ElMessageBox.prompt("修改角色描述", "编辑角色", {
      inputValue: item.description,
      inputType: "textarea",
      confirmButtonText: "保存",
      cancelButtonText: "取消",
    });
    await api.updateCharacter(item.id, { description: result.value });
    await loadLibrary();
  } catch {
    /* cancelled */
  }
}
async function archiveCharacter(item: Character) {
  try {
    await ElMessageBox.confirm(`归档角色“${item.name}”？`, `归档角色`, {
      confirmButtonText: "归档",
      cancelButtonText: "取消",
    });
    await api.deleteCharacter(item.id);
    await loadLibrary();
  } catch {
    /* cancelled */
  }
}
</script>

<template>
  <main
    class="workspace-page"
    data-testid="workspace-page-library"
    v-loading="loading"
  >
    <Teleport key="library-actions" to="#project-workspace-actions"
      ><el-button type="primary" :icon="Plus" @click="openCharacterDialog"
        >新建角色</el-button
      ><el-button :icon="Refresh" @click="loadLibrary"
        >刷新</el-button
      ></Teleport
    >
    <el-tabs v-model="activeTab"
      ><el-tab-pane label="角色" name="characters"
        ><div class="tab-header">
          <div>
            <h2>角色</h2>
            <p>参考图将用于保持镜头之间的角色连续性。</p>
          </div>
        </div>
        <el-empty
          v-if="!characters.length"
          description="暂无角色，上传参考图片创建第一个角色"
        />
        <section v-else class="card-grid">
          <article
            v-for="item in characters"
            :key="item.id"
            class="library-card"
          >
            <img
              v-if="item.primary_reference_asset_id"
              :src="api.mediaUrl(item.primary_reference_asset_id)"
              :alt="`${item.name} 主参考图`"
            />
            <div v-else class="image-empty"><Picture />暂无参考图</div>
            <div class="card-body">
              <h3>{{ item.name }}</h3>
              <p>{{ item.description || "暂无角色描述" }}</p>
              <div class="metrics">
                <span>关联镜头：{{ item.usage_count }}</span
                ><span
                  >参考图：{{ item.reference_count }} 张 · 主参考图：{{
                    item.primary_reference_asset_id ? "1 张" : "暂无"
                  }}</span
                >
              </div>
              <div class="actions">
                <el-button :icon="Edit" @click="editCharacter(item)"
                  >编辑</el-button
                ><el-button
                  type="danger"
                  plain
                  :icon="Delete"
                  @click="archiveCharacter(item)"
                  >归档</el-button
                >
              </div>
            </div>
          </article>
        </section></el-tab-pane
      >
      <el-tab-pane label="场景" name="locations"
        ><div class="tab-header">
          <div>
            <h2>场景</h2>
            <p>已保存场景可在镜头规范中复用。</p>
          </div>
        </div>
        <el-empty v-if="!locations.length" description="暂无场景" />
        <section class="card-grid">
          <article v-for="item in locations" :key="item.id" class="text-card">
            <h3>{{ item.name }}</h3>
            <p>{{ item.description || "暂无场景描述" }}</p>
            <span>关联规范：{{ item.usage_count }}</span>
          </article>
        </section></el-tab-pane
      >
      <el-tab-pane label="风格" name="styles"
        ><div class="tab-header">
          <div>
            <h2>风格</h2>
            <p>统一画面风格、镜头语言和色彩。</p>
          </div>
        </div>
        <el-empty v-if="!styles.length" description="暂无风格配置" />
        <section class="card-grid">
          <article v-for="item in styles" :key="item.id" class="text-card">
            <h3>{{ item.name }}</h3>
            <p>{{ item.description || "暂无风格描述" }}</p>
            <span>关联规范：{{ item.usage_count }}</span>
          </article>
        </section></el-tab-pane
      ></el-tabs
    >
    <el-dialog v-model="dialogVisible" title="新建角色" width="min(560px, 92vw)"
      ><div class="dialog-form">
        <el-upload
          :auto-upload="false"
          :show-file-list="false"
          accept="image/png,image/jpeg,image/webp"
          :on-change="selectImage"
          ><div class="upload-box">
            <img
              v-if="previewUrl"
              :src="previewUrl"
              alt="角色参考图片预览"
            /><template v-else
              ><Picture /><span
                >上传 PNG、JPEG 或 WebP，最大 20 MB</span
              ></template
            >
          </div></el-upload
        ><label
          >名称<el-input
            v-model="characterForm.name"
            maxlength="160"
            placeholder="角色名称" /></label
        ><label
          >角色描述（可选）<el-input
            v-model="characterForm.description"
            type="textarea"
            :rows="3"
            placeholder="角色身份和背景" /></label
        ><label
          >外观描述（可选）<el-input
            v-model="characterForm.appearance"
            type="textarea"
            :rows="3"
            placeholder="发型、服装、体态等关键特征"
        /></label>
      </div>
      <template #footer
        ><el-button @click="dialogVisible = false">取消</el-button
        ><el-button
          type="primary"
          :disabled="!characterFile || !characterForm.name.trim()"
          :loading="busy"
          @click="createCharacter"
          >创建角色</el-button
        ></template
      ></el-dialog
    >
  </main>
</template>
<style scoped>
.toolbar,
.tab-header,
.actions,
.metrics {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.toolbar h1,
.tab-header h2 {
  margin: 0;
}
.toolbar p,
.tab-header p,
.library-card p,
.text-card p,
.metrics {
  color: var(--el-text-color-secondary);
}
.tab-header {
  margin: 12px 0 20px;
}
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
  gap: 16px;
}
.library-card,
.text-card {
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  overflow: hidden;
  background: var(--el-bg-color);
}
.library-card > img,
.image-empty {
  width: 100%;
  height: 190px;
  object-fit: cover;
  background: var(--el-fill-color-light);
}
.image-empty {
  display: grid;
  place-content: center;
  text-align: center;
  gap: 8px;
}
.card-body,
.text-card {
  padding: 16px;
}
.card-body h3,
.text-card h3 {
  margin: 0;
}
.metrics {
  align-items: flex-start;
  flex-direction: column;
  font-size: 13px;
  margin: 14px 0;
}
.dialog-form {
  display: grid;
  gap: 14px;
}
.dialog-form label {
  display: grid;
  gap: 7px;
  font-weight: 600;
}
.upload-box {
  width: 100%;
  height: 190px;
  border: 1px dashed var(--el-border-color);
  border-radius: 10px;
  display: grid;
  place-content: center;
  text-align: center;
  color: var(--el-text-color-secondary);
  overflow: hidden;
}
.upload-box img {
  width: 100%;
  height: 190px;
  object-fit: contain;
}
@media (max-width: 640px) {
  .toolbar,
  .tab-header {
    align-items: stretch;
    flex-direction: column;
  }
  .card-grid {
    grid-template-columns: 1fr;
  }
}
</style>
