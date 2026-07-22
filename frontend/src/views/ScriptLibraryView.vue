<script setup lang="ts">
import { DocumentAdd, Refresh, Upload } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api, type ScriptDocument, type ScriptSourceType } from "@/api/client";

const route = useRoute();
const router = useRouter();
const projectId = computed(() => Number(route.params.projectId));
const loading = ref(false);
const busy = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
const scripts = ref<ScriptDocument[]>([]);
const pasteForm = reactive({ title: "", text: "", source_type: "PASTED" as ScriptSourceType });

onMounted(() => {
  void loadScripts();
});

async function loadScripts() {
  loading.value = true;
  try {
    scripts.value = await api.listScripts(projectId.value);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Script load failed");
  } finally {
    loading.value = false;
  }
}

async function importPaste() {
  if (!pasteForm.text.trim()) return;
  await run(async () => {
    const script = await api.importScriptText(projectId.value, { ...pasteForm });
    pasteForm.title = "";
    pasteForm.text = "";
    await loadScripts();
    await router.push(`/projects/${projectId.value}/scripts/${script.id}`);
  });
}

async function importFile(event: Event) {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;
  await run(async () => {
    const script = await api.importScriptFile(projectId.value, file);
    await loadScripts();
    await router.push(`/projects/${projectId.value}/scripts/${script.id}`);
  });
  target.value = "";
}

async function archiveScript(script: ScriptDocument) {
  await run(async () => {
    await api.archiveScript(script.id);
    await loadScripts();
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
  <main class="page">
    <header class="toolbar">
      <el-button :icon="Refresh" aria-label="刷新脚本" title="刷新脚本" :loading="loading" @click="loadScripts" />
      <el-button :icon="Upload" aria-label="上传脚本" title="上传脚本" :loading="busy" @click="fileInput?.click()" />
      <input ref="fileInput" class="hidden-input" type="file" accept=".txt,.md,.fountain,.docx" @change="importFile" />
      <el-button @click="router.push(`/projects/${projectId}`)">返回项目</el-button>
    </header>

    <section class="workspace">
      <aside class="panel import-panel">
        <h2>导入脚本</h2>
        <el-input v-model="pasteForm.title" placeholder="脚本标题" />
        <el-select v-model="pasteForm.source_type">
          <el-option label="粘贴文本" value="PASTED" />
          <el-option label="纯文本" value="PLAIN_TEXT" />
          <el-option label="Markdown" value="MARKDOWN" />
          <el-option label="Fountain" value="FOUNTAIN" />
        </el-select>
        <el-input v-model="pasteForm.text" type="textarea" :rows="14" placeholder="在此粘贴脚本文本" />
        <el-button type="primary" :icon="DocumentAdd" :loading="busy" @click="importPaste">导入</el-button>
      </aside>

      <section v-loading="loading" class="script-list">
        <article v-for="script in scripts" :key="script.id" class="script-row">
          <div>
            <h3>{{ script.title }}</h3>
            <p>{{ script.source_type }} · v{{ script.version }} · {{ script.status }}</p>
            <p>{{ script.block_count }} 个文本块 · {{ script.storyboard_count }} 个分镜草稿</p>
          </div>
          <div class="row-actions">
            <el-button @click="router.push(`/projects/${projectId}/scripts/${script.id}`)">打开</el-button>
            <el-button :disabled="script.status === 'ARCHIVED'" @click="archiveScript(script)">归档</el-button>
          </div>
        </article>
      </section>
    </section>
  </main>
</template>

<style scoped>
.page { padding: 24px; }
.toolbar { display: flex; gap: 8px; margin-bottom: 16px; }
.workspace { display: grid; grid-template-columns: 360px minmax(0, 1fr); gap: 16px; }
.panel, .script-row { border: 1px solid var(--el-border-color); border-radius: 8px; padding: 16px; background: var(--el-bg-color); }
.import-panel { display: flex; flex-direction: column; gap: 12px; }
.script-list { display: grid; gap: 12px; align-content: start; }
.script-row { display: flex; justify-content: space-between; gap: 16px; }
.script-row h3 { margin: 0 0 6px; }
.script-row p { margin: 0 0 4px; color: var(--el-text-color-secondary); }
.row-actions { display: flex; align-items: center; gap: 8px; }
.hidden-input { display: none; }
@media (max-width: 900px) { .workspace { grid-template-columns: 1fr; } }
</style>
