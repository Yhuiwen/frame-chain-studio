<script setup lang="ts">
import { Plus, Refresh } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import {
  api,
  type Character,
  type Location,
  type ShotCharacterSpec,
  type ShotSpec,
  type ShotSpecPatch,
  type StyleProfile,
} from "@/api/client";

const route = useRoute();
const router = useRouter();
const projectId = computed(() => Number(route.params.projectId));
const shotId = computed(() => Number(route.params.shotId));
const loading = ref(false);
const busy = ref(false);
const spec = ref<ShotSpec | null>(null);
const history = ref<ShotSpec[]>([]);
const characters = ref<Character[]>([]);
const locations = ref<Location[]>([]);
const styles = ref<StyleProfile[]>([]);
const selectedCharacterId = ref<number | null>(null);
const reason = ref("structured spec update");
const form = reactive<ShotSpecPatch>({
  location_id: null,
  style_profile_id: null,
  summary: "",
  action: "",
  emotion: "",
  composition: "",
  shot_size: "",
  camera_angle: "",
  camera_movement: "",
  lighting: "",
  time_of_day: "",
  weather: "",
  dialogue: "",
  continuity_notes: "",
  props: [],
  provider_overrides: {},
});
const characterRows = ref<ShotCharacterSpec[]>([]);
const propsText = ref("");
const overridesText = ref("{}");

onMounted(() => {
  void loadAll();
});

async function loadAll() {
  loading.value = true;
  try {
    const [nextSpec, nextHistory, nextCharacters, nextLocations, nextStyles] = await Promise.all([
      api.getShotSpec(shotId.value),
      api.listShotSpecHistory(shotId.value),
      api.listCharacters(projectId.value),
      api.listLocations(projectId.value),
      api.listStyleProfiles(projectId.value),
    ]);
    spec.value = nextSpec;
    history.value = nextHistory;
    characters.value = nextCharacters;
    locations.value = nextLocations;
    styles.value = nextStyles;
    Object.assign(form, {
      location_id: nextSpec.location_id,
      style_profile_id: nextSpec.style_profile_id,
      summary: nextSpec.summary,
      action: nextSpec.action,
      emotion: nextSpec.emotion,
      composition: nextSpec.composition,
      shot_size: nextSpec.shot_size,
      camera_angle: nextSpec.camera_angle,
      camera_movement: nextSpec.camera_movement,
      lighting: nextSpec.lighting,
      time_of_day: nextSpec.time_of_day,
      weather: nextSpec.weather,
      dialogue: nextSpec.dialogue,
      continuity_notes: nextSpec.continuity_notes,
      props: [...nextSpec.props],
      provider_overrides: { ...nextSpec.provider_overrides },
    });
    characterRows.value = nextSpec.characters.map((item) => ({ ...item, props: [...item.props], reference_asset_ids: [...item.reference_asset_ids] }));
    propsText.value = nextSpec.props.join("\n");
    overridesText.value = JSON.stringify(nextSpec.provider_overrides, null, 2);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Shot spec load failed");
  } finally {
    loading.value = false;
  }
}

function addCharacter() {
  if (!selectedCharacterId.value || characterRows.value.some((item) => item.character_id === selectedCharacterId.value)) return;
  characterRows.value.push({
    character_id: selectedCharacterId.value,
    role: "SECONDARY",
    sort_order: characterRows.value.length,
    appearance_override: "",
    clothing_override: "",
    expression: "",
    action: "",
    position: "",
    props: [],
    continuity_notes: "",
    reference_asset_ids: [],
  });
  selectedCharacterId.value = null;
}

function removeCharacter(index: number) {
  characterRows.value.splice(index, 1);
  characterRows.value.forEach((item, rowIndex) => {
    item.sort_order = rowIndex;
  });
}

function characterName(characterId: number) {
  return characters.value.find((item) => item.id === characterId)?.name ?? `Character #${characterId}`;
}

function parseList(value: string) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseOverrides() {
  try {
    const parsed = JSON.parse(overridesText.value || "{}") as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : {};
  } catch {
    throw new Error("Provider overrides must be valid JSON object");
  }
}

function cleanCharacters() {
  return characterRows.value.map((item, index) => ({
    character_id: item.character_id,
    role: item.role,
    sort_order: index,
    appearance_override: item.appearance_override,
    clothing_override: item.clothing_override,
    expression: item.expression,
    action: item.action,
    position: item.position,
    props: item.props,
    continuity_notes: item.continuity_notes,
    reference_asset_ids: item.reference_asset_ids,
  }));
}

async function saveRevision() {
  busy.value = true;
  try {
    const changes: ShotSpecPatch = {
      ...form,
      props: parseList(propsText.value),
      provider_overrides: parseOverrides(),
    };
    await api.reviseShotSpec(shotId.value, { reason: reason.value, changes, characters: cleanCharacters() });
    await loadAll();
    ElMessage.success("ShotSpec revision saved");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Save failed");
  } finally {
    busy.value = false;
  }
}

async function syncSpec() {
  busy.value = true;
  try {
    await api.syncShotSpec(shotId.value, { reason: "sync structured defaults" });
    await loadAll();
    ElMessage.success("ShotSpec synced");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Sync failed");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="page" v-loading="loading">
    <section class="toolbar">
      <div>
        <h1>Shot Spec</h1>
        <p v-if="spec">Revision {{ spec.revision }} · {{ spec.compiler_version }}</p>
      </div>
      <div class="actions">
        <el-button native-type="button" @click="router.push(`/projects/${projectId}`)">Project</el-button>
        <el-button native-type="button" :icon="Refresh" :loading="loading" @click="loadAll">Refresh</el-button>
        <el-button native-type="button" :loading="busy" @click="syncSpec">Sync Defaults</el-button>
        <el-button native-type="button" type="primary" :loading="busy" @click="saveRevision">Save Revision</el-button>
      </div>
    </section>

    <section v-if="spec" class="spec-layout">
      <div class="editor-panel">
        <div class="field-row">
          <label>
            Location
            <el-select v-model="form.location_id" clearable>
              <el-option v-for="item in locations" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </label>
          <label>
            Style
            <el-select v-model="form.style_profile_id" clearable>
              <el-option v-for="item in styles" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </label>
        </div>
        <el-input v-model="reason" placeholder="Revision reason" />
        <el-input v-model="form.summary" type="textarea" :rows="2" placeholder="Summary" />
        <el-input v-model="form.action" type="textarea" :rows="2" placeholder="Action" />
        <el-input v-model="form.emotion" placeholder="Emotion" />
        <div class="field-row">
          <el-input v-model="form.composition" placeholder="Composition" />
          <el-input v-model="form.shot_size" placeholder="Shot size" />
          <el-input v-model="form.camera_angle" placeholder="Camera angle" />
        </div>
        <el-input v-model="form.camera_movement" placeholder="Camera movement" />
        <div class="field-row">
          <el-input v-model="form.lighting" placeholder="Lighting" />
          <el-input v-model="form.time_of_day" placeholder="Time of day" />
          <el-input v-model="form.weather" placeholder="Weather" />
        </div>
        <el-input v-model="form.dialogue" type="textarea" :rows="2" placeholder="Dialogue" />
        <el-input v-model="form.continuity_notes" type="textarea" :rows="3" placeholder="Continuity notes" />
        <el-input v-model="propsText" type="textarea" :rows="3" placeholder="Props, one per line" />
        <el-input v-model="overridesText" type="textarea" :rows="4" placeholder="Provider overrides JSON" />
      </div>

      <div class="characters-panel">
        <div class="panel-title">
          <h2>Characters</h2>
          <div class="add-row">
            <el-select v-model="selectedCharacterId" placeholder="Add character" clearable>
              <el-option v-for="item in characters" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
            <el-button native-type="button" :icon="Plus" @click="addCharacter">Add</el-button>
          </div>
        </div>
        <article v-for="(item, index) in characterRows" :key="item.character_id" class="character-card">
          <div class="card-title">
            <strong>{{ characterName(item.character_id) }}</strong>
            <el-select v-model="item.role">
              <el-option label="Primary" value="PRIMARY" />
              <el-option label="Secondary" value="SECONDARY" />
              <el-option label="Background" value="BACKGROUND" />
            </el-select>
          </div>
          <el-input v-model="item.appearance_override" placeholder="Appearance override" />
          <el-input v-model="item.clothing_override" placeholder="Clothing override" />
          <el-input v-model="item.expression" placeholder="Expression" />
          <el-input v-model="item.action" placeholder="Action" />
          <el-input v-model="item.position" placeholder="Position" />
          <el-input v-model="item.continuity_notes" type="textarea" :rows="2" placeholder="Continuity notes" />
          <el-button native-type="button" type="danger" @click="removeCharacter(index)">Remove</el-button>
        </article>
      </div>

      <div class="preview-panel">
        <div class="panel-title">
          <h2>Compiled Prompt</h2>
          <el-tag size="small">{{ spec.reference_asset_ids.length }} refs</el-tag>
        </div>
        <pre>{{ spec.compiled_prompt }}</pre>
        <h3>Negative</h3>
        <pre>{{ spec.compiled_negative_prompt || "none" }}</pre>
        <h3>Structured Payload</h3>
        <pre>{{ JSON.stringify(spec.structured_payload, null, 2) }}</pre>
      </div>

      <div class="history-panel">
        <h2>History</h2>
        <el-timeline>
          <el-timeline-item v-for="item in history" :key="item.id" :timestamp="item.created_at">
            Revision {{ item.revision }} · {{ item.compiler_version }}
          </el-timeline-item>
        </el-timeline>
      </div>
    </section>
  </main>
</template>

<style scoped>
.actions,
.add-row,
.card-title,
.field-row,
.panel-title {
  align-items: center;
  display: flex;
  gap: 10px;
}

.actions,
.panel-title {
  justify-content: flex-end;
}

.spec-layout {
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr);
}

.editor-panel,
.characters-panel,
.preview-panel,
.history-panel {
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  display: grid;
  gap: 10px;
  padding: 14px;
}

.field-row label {
  color: var(--el-text-color-secondary);
  display: grid;
  flex: 1;
  font-size: 12px;
  gap: 6px;
}

.character-card {
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  display: grid;
  gap: 8px;
  padding: 10px;
}

.card-title {
  justify-content: space-between;
}

.preview-panel,
.history-panel {
  align-content: start;
}

pre {
  background: var(--el-fill-color-light);
  border-radius: 6px;
  margin: 0;
  max-height: 360px;
  overflow: auto;
  padding: 12px;
  white-space: pre-wrap;
}

h2,
h3 {
  margin: 0;
}

@media (max-width: 960px) {
  .actions,
  .field-row,
  .spec-layout {
    align-items: stretch;
    display: flex;
    flex-direction: column;
  }
}
</style>
