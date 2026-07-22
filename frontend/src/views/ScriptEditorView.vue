<script setup lang="ts">
import { Refresh } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api, type ScriptBlock, type ScriptBlockType, type ScriptContent, type ScriptDocument, type StoryboardDraft } from "@/api/client";

const route = useRoute();
const router = useRouter();
const projectId = computed(() => Number(route.params.projectId));
const scriptId = computed(() => Number(route.params.scriptId));
const loading = ref(false);
const busy = ref(false);
const script = ref<ScriptDocument | null>(null);
const content = ref<ScriptContent | null>(null);
const blocks = ref<ScriptBlock[]>([]);
const storyboards = ref<StoryboardDraft[]>([]);
const blockTypes: ScriptBlockType[] = ["SCENE_HEADING", "ACTION", "DIALOGUE", "CHARACTER_CUE", "PARENTHETICAL", "TRANSITION", "COMMENT", "UNKNOWN"];

onMounted(() => {
  void loadAll();
});

async function loadAll() {
  loading.value = true;
  try {
    const [nextScript, nextContent, nextBlocks, nextStoryboards] = await Promise.all([
      api.getScript(scriptId.value),
      api.getScriptContent(scriptId.value),
      api.listScriptBlocks(scriptId.value),
      api.listStoryboards(scriptId.value),
    ]);
    script.value = nextScript;
    content.value = nextContent;
    blocks.value = nextBlocks;
    storyboards.value = nextStoryboards;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Script load failed");
  } finally {
    loading.value = false;
  }
}

async function parseNow() {
  await run(async () => {
    await api.parseScript(scriptId.value);
    await loadAll();
  });
}

async function updateBlock(block: ScriptBlock, type: ScriptBlockType | null) {
  await run(async () => {
    await api.updateScriptBlock(block.id, { user_block_type: type });
    await loadAll();
  });
}

async function confirmWarnings(block: ScriptBlock) {
  await run(async () => {
    await api.updateScriptBlock(block.id, { warnings_confirmed: true });
    await loadAll();
  });
}

async function createStoryboard() {
  await run(async () => {
    const storyboard = await api.createStoryboard(scriptId.value, { name: `${script.value?.title ?? "Script"} Storyboard` });
    await router.push(`/projects/${projectId.value}/storyboards/${storyboard.id}`);
  });
}

async function run(action: () => Promise<void>) {
  busy.value = true;
  try {
    await action();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Script operation failed");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main v-loading="loading" class="page">
    <header class="toolbar">
      <el-button :icon="Refresh" :loading="busy" @click="parseNow">解析脚本</el-button>
      <el-button type="primary" :loading="busy" @click="createStoryboard">新建分镜草稿</el-button>
      <el-button @click="router.push(`/projects/${projectId}/scripts`)">返回脚本列表</el-button>
    </header>

    <section class="editor-grid">
      <section class="panel raw-text">
        <h2>{{ script?.title }}</h2>
        <pre>{{ content?.raw_text }}</pre>
      </section>

      <section class="panel blocks">
        <article v-for="block in blocks" :key="block.id" class="block-row">
          <div class="block-meta">
            <span>#{{ block.sort_order + 1 }}</span>
            <el-select :model-value="block.user_block_type ?? block.block_type" @change="(value: ScriptBlockType) => updateBlock(block, value)">
              <el-option v-for="type in blockTypes" :key="type" :label="type" :value="type" />
            </el-select>
          </div>
          <p>{{ block.effective_text }}</p>
          <small>{{ block.source_start }}-{{ block.source_end }} · {{ block.speaker || "no speaker" }}</small>
          <el-button v-if="block.parse_warnings.length && !block.warnings_confirmed" size="small" @click="confirmWarnings(block)">确认警告</el-button>
        </article>
      </section>

      <aside class="panel side">
        <h2>分镜审核</h2>
        <p>状态：{{ script?.status }}</p>
        <p>解析器版本：{{ script?.parse_revision }}</p>
        <p>文本块：{{ blocks.length }}</p>
        <p>分镜稿：{{ storyboards.length }}</p>
        <article v-for="storyboard in storyboards" :key="storyboard.id" class="storyboard-row">
          <strong>{{ storyboard.name }}</strong>
          <span>{{ storyboard.status }} · {{ storyboard.shot_draft_count }} drafts</span>
          <el-button size="small" @click="router.push(`/projects/${projectId}/storyboards/${storyboard.id}`)">打开</el-button>
        </article>
      </aside>
    </section>
  </main>
</template>

<style scoped>
.page { padding: 24px; }
.toolbar { display: flex; gap: 8px; margin-bottom: 16px; }
.editor-grid { display: grid; grid-template-columns: minmax(260px, 1fr) minmax(320px, 1.1fr) 280px; gap: 16px; }
.panel { border: 1px solid var(--el-border-color); border-radius: 8px; padding: 16px; background: var(--el-bg-color); min-width: 0; }
.raw-text pre { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.blocks { display: grid; gap: 10px; align-content: start; }
.block-row { border-bottom: 1px solid var(--el-border-color-lighter); padding-bottom: 10px; }
.block-meta { display: grid; grid-template-columns: 48px minmax(0, 1fr); gap: 8px; align-items: center; }
.block-row p { margin: 8px 0; }
.block-row small, .side p, .storyboard-row span { color: var(--el-text-color-secondary); }
.storyboard-row { display: grid; gap: 6px; margin-top: 12px; }
@media (max-width: 1100px) { .editor-grid { grid-template-columns: 1fr; } }
</style>
