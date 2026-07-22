<script setup lang="ts">
import { Delete, DocumentAdd, Picture, Refresh } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api, type Character, type Location, type StyleProfile } from "@/api/client";

const route = useRoute();
const router = useRouter();
const projectId = computed(() => Number(route.params.projectId));
const loading = ref(false);
const busy = ref(false);
const activeTab = ref("characters");
const characters = ref<Character[]>([]);
const locations = ref<Location[]>([]);
const styles = ref<StyleProfile[]>([]);
const selectedReferenceTarget = reactive({ type: "character" as "character" | "location", id: 0 });
const referenceInput = ref<HTMLInputElement | null>(null);

const characterForm = reactive({
  name: "",
  description: "",
  appearance: "",
  personality: "",
  default_clothing: "",
  continuity_notes: "",
});
const locationForm = reactive({
  name: "",
  description: "",
  environment: "",
  architecture: "",
  time_of_day: "",
  weather: "",
  lighting: "",
  continuity_notes: "",
});
const styleForm = reactive({
  name: "",
  description: "",
  positive_prompt: "",
  negative_prompt: "",
  rendering_style: "",
  camera_language: "",
  aspect_ratio: "16:9",
  fps: null as number | null,
});

onMounted(() => {
  void loadLibrary();
});

async function loadLibrary() {
  loading.value = true;
  try {
    const [nextCharacters, nextLocations, nextStyles] = await Promise.all([
      api.listCharacters(projectId.value),
      api.listLocations(projectId.value),
      api.listStyleProfiles(projectId.value),
    ]);
    characters.value = nextCharacters;
    locations.value = nextLocations;
    styles.value = nextStyles;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Library load failed");
  } finally {
    loading.value = false;
  }
}

async function createCharacter() {
  if (!characterForm.name.trim()) return;
  await run(async () => {
    await api.createCharacter(projectId.value, { ...characterForm });
    Object.assign(characterForm, {
      name: "",
      description: "",
      appearance: "",
      personality: "",
      default_clothing: "",
      continuity_notes: "",
    });
  });
}

async function createLocation() {
  if (!locationForm.name.trim()) return;
  await run(async () => {
    await api.createLocation(projectId.value, { ...locationForm });
    Object.assign(locationForm, {
      name: "",
      description: "",
      environment: "",
      architecture: "",
      time_of_day: "",
      weather: "",
      lighting: "",
      continuity_notes: "",
    });
  });
}

async function createStyle() {
  if (!styleForm.name.trim()) return;
  await run(async () => {
    await api.createStyleProfile(projectId.value, { ...styleForm });
    Object.assign(styleForm, {
      name: "",
      description: "",
      positive_prompt: "",
      negative_prompt: "",
      rendering_style: "",
      camera_language: "",
      aspect_ratio: "16:9",
      fps: null,
    });
  });
}

async function saveCharacter(item: Character) {
  await run(() => api.updateCharacter(item.id, item));
}

async function saveLocation(item: Location) {
  await run(() => api.updateLocation(item.id, item));
}

async function saveStyle(item: StyleProfile) {
  await run(() => api.updateStyleProfile(item.id, item));
}

async function archiveCharacter(id: number) {
  await run(() => api.deleteCharacter(id));
}

async function archiveLocation(id: number) {
  await run(() => api.deleteLocation(id));
}

async function archiveStyle(id: number) {
  await run(() => api.deleteStyleProfile(id));
}

function chooseReference(type: "character" | "location", id: number) {
  selectedReferenceTarget.type = type;
  selectedReferenceTarget.id = id;
  referenceInput.value?.click();
}

async function uploadReference(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file || !selectedReferenceTarget.id) return;
  await run(async () => {
    const asset = await api.uploadProjectImage(projectId.value, file);
    if (selectedReferenceTarget.type === "character") {
      await api.addCharacterReference(selectedReferenceTarget.id, { asset_id: asset.id, reference_type: "FACE", is_primary: true });
    } else {
      await api.addLocationReference(selectedReferenceTarget.id, { asset_id: asset.id, reference_type: "WIDE", is_primary: true });
    }
  });
  (event.target as HTMLInputElement).value = "";
}

async function run(action: () => Promise<unknown>) {
  busy.value = true;
  try {
    await action();
    await loadLibrary();
    ElMessage.success("Saved");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Save failed");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="page" v-loading="loading">
    <section class="toolbar">
      <div>
        <h1>连续性资料库</h1>
        <p>管理当前项目中的角色、场景和可复用风格配置。</p>
      </div>
      <div class="actions">
        <input ref="referenceInput" class="hidden-input" type="file" accept="image/png,image/jpeg,image/webp" @change="uploadReference" />
        <el-button native-type="button" @click="router.push(`/projects/${projectId}`)">返回项目</el-button>
        <el-button native-type="button" :icon="Refresh" :loading="loading" @click="loadLibrary">刷新</el-button>
      </div>
    </section>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="角色" name="characters">
        <section class="create-row">
          <el-input v-model="characterForm.name" placeholder="Name" />
          <el-input v-model="characterForm.appearance" placeholder="Appearance" />
          <el-input v-model="characterForm.default_clothing" placeholder="Default clothing" />
          <el-button native-type="button" type="primary" :icon="DocumentAdd" :loading="busy" @click="createCharacter">新建角色</el-button>
        </section>
        <section class="library-list">
          <article v-for="item in characters" :key="item.id" class="library-card">
            <div class="card-title">
              <el-input v-model="item.name" />
              <el-tag size="small">{{ item.usage_count }} shots</el-tag>
            </div>
            <el-input v-model="item.description" type="textarea" :rows="2" placeholder="Description" />
            <el-input v-model="item.appearance" type="textarea" :rows="2" placeholder="Appearance" />
            <el-input v-model="item.personality" placeholder="Personality" />
            <el-input v-model="item.default_clothing" placeholder="Default clothing" />
            <el-input v-model="item.continuity_notes" type="textarea" :rows="2" placeholder="Continuity notes" />
            <div class="card-actions">
              <span>{{ item.reference_count }} refs · primary {{ item.primary_reference_asset_id ?? "none" }}</span>
              <el-button native-type="button" :icon="Picture" @click="chooseReference('character', item.id)">参考图</el-button>
              <el-button native-type="button" type="primary" :loading="busy" @click="saveCharacter(item)">保存</el-button>
              <el-button native-type="button" type="danger" :icon="Delete" @click="archiveCharacter(item.id)">归档</el-button>
            </div>
          </article>
        </section>
      </el-tab-pane>

      <el-tab-pane label="场景" name="locations">
        <section class="create-row">
          <el-input v-model="locationForm.name" placeholder="Name" />
          <el-input v-model="locationForm.description" placeholder="Description" />
          <el-input v-model="locationForm.lighting" placeholder="Lighting" />
          <el-button native-type="button" type="primary" :icon="DocumentAdd" :loading="busy" @click="createLocation">新建场景</el-button>
        </section>
        <section class="library-list">
          <article v-for="item in locations" :key="item.id" class="library-card">
            <div class="card-title">
              <el-input v-model="item.name" />
              <el-tag size="small">{{ item.usage_count }} specs</el-tag>
            </div>
            <el-input v-model="item.description" type="textarea" :rows="2" placeholder="Description" />
            <el-input v-model="item.environment" placeholder="Environment" />
            <el-input v-model="item.architecture" placeholder="Architecture" />
            <div class="two-col">
              <el-input v-model="item.time_of_day" placeholder="Time of day" />
              <el-input v-model="item.weather" placeholder="Weather" />
            </div>
            <el-input v-model="item.lighting" type="textarea" :rows="2" placeholder="Lighting" />
            <el-input v-model="item.continuity_notes" type="textarea" :rows="2" placeholder="Continuity notes" />
            <div class="card-actions">
              <span>{{ item.reference_count }} refs · primary {{ item.primary_reference_asset_id ?? "none" }}</span>
              <el-button native-type="button" :icon="Picture" @click="chooseReference('location', item.id)">参考图</el-button>
              <el-button native-type="button" type="primary" :loading="busy" @click="saveLocation(item)">保存</el-button>
              <el-button native-type="button" type="danger" :icon="Delete" @click="archiveLocation(item.id)">归档</el-button>
            </div>
          </article>
        </section>
      </el-tab-pane>

      <el-tab-pane label="风格" name="styles">
        <section class="create-row">
          <el-input v-model="styleForm.name" placeholder="Name" />
          <el-input v-model="styleForm.positive_prompt" placeholder="Positive prompt" />
          <el-input v-model="styleForm.negative_prompt" placeholder="Negative prompt" />
          <el-button native-type="button" type="primary" :icon="DocumentAdd" :loading="busy" @click="createStyle">新建风格</el-button>
        </section>
        <section class="library-list">
          <article v-for="item in styles" :key="item.id" class="library-card">
            <div class="card-title">
              <el-input v-model="item.name" />
              <el-tag size="small">{{ item.usage_count }} specs</el-tag>
            </div>
            <el-input v-model="item.description" type="textarea" :rows="2" placeholder="Description" />
            <el-input v-model="item.positive_prompt" type="textarea" :rows="2" placeholder="Positive prompt" />
            <el-input v-model="item.negative_prompt" type="textarea" :rows="2" placeholder="Negative prompt" />
            <el-input v-model="item.rendering_style" placeholder="Rendering style" />
            <el-input v-model="item.camera_language" placeholder="Camera language" />
            <div class="two-col">
              <el-input v-model="item.aspect_ratio" placeholder="Aspect ratio" />
              <el-input-number v-model="item.fps" :min="1" placeholder="FPS" />
            </div>
            <div class="card-actions">
              <span>{{ item.color_palette.join(", ") || "No palette" }}</span>
              <el-button native-type="button" type="primary" :loading="busy" @click="saveStyle(item)">保存</el-button>
              <el-button native-type="button" type="danger" :icon="Delete" @click="archiveStyle(item.id)">归档</el-button>
            </div>
          </article>
        </section>
      </el-tab-pane>
    </el-tabs>
  </main>
</template>

<style scoped>
.actions,
.card-actions,
.card-title,
.create-row,
.two-col {
  align-items: center;
  display: flex;
  gap: 10px;
}

.create-row {
  margin: 0 0 16px;
}

.library-list {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
}

.library-card {
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  display: grid;
  gap: 10px;
  padding: 14px;
}

.card-title {
  justify-content: space-between;
}

.card-actions {
  color: var(--el-text-color-secondary);
  flex-wrap: wrap;
  font-size: 12px;
  justify-content: flex-end;
}

.two-col {
  align-items: stretch;
}

.hidden-input {
  display: none;
}

@media (max-width: 760px) {
  .actions,
  .create-row,
  .two-col {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
