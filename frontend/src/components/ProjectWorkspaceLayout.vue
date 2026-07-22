<script setup lang="ts">
import { Menu } from "@element-plus/icons-vue";
import { ref } from "vue";
import { useRouter } from "vue-router";

import ProjectWorkspaceNav from "@/components/ProjectWorkspaceNav.vue";

defineProps<{
  projectId: number;
  projectName: string;
  projectStatus: string;
  pageTitle: string;
  shotId?: number;
}>();

const drawerOpen = ref(false);
const router = useRouter();
</script>

<template>
  <div class="project-shell">
    <aside class="project-shell__sidebar">
      <div class="brand">帧链工作室</div>
      <el-tooltip :content="projectName" placement="right">
        <h2>{{ projectName }}</h2>
      </el-tooltip>
      <el-tag size="small">{{ projectStatus }}</el-tag>
      <ProjectWorkspaceNav :project-id="projectId" :shot-id="shotId" embedded />
      <footer>
        <button @click="router.push({ name: 'project-detail', params: { id: projectId } })">项目设置</button>
        <button @click="router.push({ name: 'projects' })">返回项目列表</button>
        <span>模拟服务商环境</span>
      </footer>
    </aside>

    <section class="project-shell__main">
      <header class="project-shell__header">
        <el-button class="mobile-menu" :icon="Menu" circle aria-label="打开项目导航" @click="drawerOpen = true" />
        <div class="project-shell__heading">
          <small>{{ projectName }}</small>
          <h1>{{ pageTitle }}</h1>
        </div>
        <div class="project-shell__actions"><slot name="actions" /></div>
      </header>
      <main class="project-shell__content"><slot /></main>
    </section>

    <el-drawer v-model="drawerOpen" direction="ltr" size="min(320px, 86vw)" title="项目导航">
      <ProjectWorkspaceNav :project-id="projectId" :shot-id="shotId" embedded />
    </el-drawer>
  </div>
</template>

<style scoped>
.project-shell { display: grid; grid-template-columns: 216px minmax(0, 1fr); width: 100%; height: 100dvh; overflow: hidden; background: var(--app-bg); }
.project-shell__sidebar { height: 100dvh; min-width: 0; overflow: hidden; padding: 22px 14px 16px; background: var(--surface); border-right: 1px solid var(--border); box-shadow: 3px 0 14px rgb(16 24 40 / 4%); display: grid; grid-template-rows: auto auto auto minmax(0, 1fr) auto; gap: 10px; }
.brand { font-weight: 800; color: var(--primary); padding: 0 10px 8px; }
.project-shell__sidebar h2 { margin: 0; padding: 0 10px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.project-shell__sidebar :deep(.project-workspace-nav) { margin-top: 10px; align-content: start; }
.project-shell__sidebar footer { display: grid; gap: 6px; border-top: 1px solid var(--border); padding-top: 12px; }
.project-shell__sidebar footer button { border: 0; background: transparent; text-align: left; padding: 8px 10px; color: var(--muted); cursor: pointer; }
.project-shell__sidebar footer span { font-size: 11px; color: var(--muted); padding: 6px 10px; }
.project-shell__main { min-width: 0; height: 100dvh; display: grid; grid-template-rows: auto minmax(0, 1fr); overflow: hidden; }
.project-shell__header { min-width: 0; min-height: 76px; padding: 14px 24px; background: var(--surface); border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 14px; justify-content: space-between; }
.project-shell__heading { min-width: 0; }
.project-shell__header small { color: var(--muted); }
.project-shell__header h1 { margin: 2px 0 0; font-size: 22px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.project-shell__actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.project-shell__content { min-width: 0; min-height: 0; overflow: auto; overscroll-behavior: contain; }
.mobile-menu { display: none; }
@media (max-width: 900px) {
  .project-shell { grid-template-columns: minmax(0, 1fr); }
  .project-shell__sidebar { display: none; }
  .mobile-menu { display: inline-flex; }
  .project-shell__header { padding: 10px 14px; min-height: 64px; }
  .project-shell__header h1 { font-size: 18px; }
}
</style>
