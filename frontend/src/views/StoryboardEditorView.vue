<script setup lang="ts">
import { Refresh } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api, type Character, type Location, type ShotDraft, type ShotDraftPreview, type StoryboardDraft, type StyleProfile } from "@/api/client";

const route = useRoute();
const router = useRouter();
const projectId = computed(() => Number(route.params.projectId));
const storyboardId = computed(() => Number(route.params.storyboardId));
const loading = ref(false);
const busy = ref(false);
const storyboard = ref<StoryboardDraft | null>(null);
const drafts = ref<ShotDraft[]>([]);
const characters = ref<Character[]>([]);
const locations = ref<Location[]>([]);
const styles = ref<StyleProfile[]>([]);
const selectedIds = ref<number[]>([]);
const preview = ref<ShotDraftPreview | null>(null);
const edit = reactive<Partial<ShotDraft>>({});

onMounted(() => {
  void loadAll();
});

async function loadAll() {
  loading.value = true;
  try {
    const [nextStoryboard, nextDrafts, nextCharacters, nextLocations, nextStyles] = await Promise.all([
      api.getStoryboard(storyboardId.value),
      api.listShotDrafts(storyboardId.value),
      api.listCharacters(projectId.value),
      api.listLocations(projectId.value),
      api.listStyleProfiles(projectId.value),
    ]);
    storyboard.value = nextStoryboard;
    drafts.value = nextDrafts;
    characters.value = nextCharacters;
    locations.value = nextLocations;
    styles.value = nextStyles;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Storyboard load failed");
  } finally {
    loading.value = false;
  }
}

function startEdit(draft: ShotDraft) {
  Object.assign(edit, JSON.parse(JSON.stringify(draft)) as ShotDraft);
}

async function saveEdit() {
  if (!edit.id) return;
  await run(async () => {
    await api.updateShotDraft(edit.id as number, edit);
    preview.value = null;
    await loadAll();
  });
}

async function previewDraft(draft: ShotDraft) {
  await run(async () => {
    preview.value = await api.previewShotDraft(draft.id);
  });
}

async function splitDraft(draft: ShotDraft) {
  if (!draft.source_block_start_id) return;
  await run(async () => {
    await api.splitShotDraft(draft.id, { split_after_block_id: draft.source_block_start_id });
    await loadAll();
  });
}

async function applyDraft(draft: ShotDraft) {
  await run(async () => {
    await api.applyShotDraft(draft.id);
    await loadAll();
  });
}

async function applySelected() {
  if (!selectedIds.value.length) return;
  await run(async () => {
    await api.applyStoryboard(storyboardId.value, { shot_draft_ids: selectedIds.value });
    selectedIds.value = [];
    await loadAll();
  });
}

async function run(action: () => Promise<void>) {
  busy.value = true;
  try {
    await action();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Storyboard operation failed");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main v-loading="loading" class="page">
    <header class="toolbar">
      <el-button :icon="Refresh" :loading="loading" @click="loadAll" />
      <el-button type="primary" :disabled="!selectedIds.length" :loading="busy" @click="applySelected">Apply Selected</el-button>
      <el-button @click="router.push(`/projects/${projectId}/scripts/${storyboard?.script_document_id}`)">Script</el-button>
    </header>

    <section class="board">
      <section class="drafts">
        <article v-for="draft in drafts" :key="draft.id" class="draft-card">
          <header>
            <el-checkbox v-model="selectedIds" :label="draft.id" :disabled="draft.status === 'APPLIED' || draft.status === 'SKIPPED'">#{{ draft.sort_order + 1 }}</el-checkbox>
            <el-tag>{{ draft.status }}</el-tag>
          </header>
          <h3>{{ draft.title }}</h3>
          <p>{{ draft.summary }}</p>
          <small>{{ draft.source_text }}</small>
          <div class="actions">
            <el-button size="small" @click="startEdit(draft)">Edit</el-button>
            <el-button size="small" @click="previewDraft(draft)">Preview</el-button>
            <el-button size="small" :disabled="draft.status === 'APPLIED'" @click="splitDraft(draft)">Split</el-button>
            <el-button size="small" :disabled="draft.status === 'APPLIED'" @click="api.mergeShotDraftNext(draft.id).then(loadAll)">Merge</el-button>
            <el-button size="small" :disabled="draft.status === 'APPLIED'" @click="api.skipShotDraft(draft.id).then(loadAll)">Skip</el-button>
            <el-button size="small" :disabled="draft.status === 'APPLIED'" @click="api.restoreShotDraft(draft.id).then(loadAll)">Restore</el-button>
            <el-button size="small" type="primary" :disabled="draft.status === 'APPLIED' || draft.status === 'SKIPPED'" @click="applyDraft(draft)">Apply</el-button>
          </div>
        </article>
      </section>

      <aside class="side">
        <section class="panel">
          <h2>Edit Draft</h2>
          <el-input v-model="edit.title" placeholder="Title" />
          <el-input v-model="edit.summary" type="textarea" :rows="3" placeholder="Summary" />
          <el-input v-model="edit.action" type="textarea" :rows="3" placeholder="Action" />
          <el-input v-model="edit.dialogue" type="textarea" :rows="3" placeholder="Dialogue" />
          <el-select v-model="edit.location_id" clearable placeholder="Location">
            <el-option v-for="location in locations" :key="location.id" :label="location.name" :value="location.id" />
          </el-select>
          <el-select v-model="edit.style_profile_id" clearable placeholder="Style">
            <el-option v-for="style in styles" :key="style.id" :label="style.name" :value="style.id" />
          </el-select>
          <el-input v-model="edit.free_prompt" type="textarea" :rows="3" placeholder="Free prompt" />
          <el-button type="primary" :disabled="!edit.id" :loading="busy" @click="saveEdit">Save</el-button>
        </section>

        <section class="panel">
          <h2>Characters</h2>
          <el-select v-if="edit.characters?.length" v-model="edit.characters[0].character_id" clearable placeholder="Character">
            <el-option v-for="character in characters" :key="character.id" :label="character.name" :value="character.id" />
          </el-select>
          <p v-else>No parsed character row selected.</p>
        </section>

        <section class="panel preview">
          <h2>Prompt Preview</h2>
          <p>{{ preview?.compiler_version }}</p>
          <pre>{{ preview?.compiled_prompt }}</pre>
        </section>
      </aside>
    </section>
  </main>
</template>

<style scoped>
.page { padding: 24px; }
.toolbar { display: flex; gap: 8px; margin-bottom: 16px; }
.board { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 16px; align-items: start; }
.drafts { display: grid; gap: 12px; }
.draft-card, .panel { border: 1px solid var(--el-border-color); border-radius: 8px; padding: 16px; background: var(--el-bg-color); }
.draft-card header { display: flex; justify-content: space-between; align-items: center; }
.draft-card h3 { margin: 10px 0 6px; }
.draft-card p { margin: 0 0 8px; }
.draft-card small { display: block; color: var(--el-text-color-secondary); white-space: pre-wrap; overflow-wrap: anywhere; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.side { display: grid; gap: 12px; }
.panel { display: grid; gap: 10px; }
.preview pre { max-height: 260px; overflow: auto; white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
@media (max-width: 1000px) { .board { grid-template-columns: 1fr; } }
</style>
