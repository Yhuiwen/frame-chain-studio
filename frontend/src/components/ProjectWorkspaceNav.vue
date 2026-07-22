<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

const props = withDefaults(defineProps<{ projectId: number; shotId?: number; embedded?: boolean }>(), { embedded: false });
const route = useRoute();
const router = useRouter();
const items = computed(() => [
  { label: "项目工作台", name: "project-detail", params: { id: props.projectId }, active: route.name === "project-detail" },
  { label: "连续性资料库", name: "project-library", params: { projectId: props.projectId }, active: route.name === "project-library" },
  { label: "脚本与分镜", name: "script-library", params: { projectId: props.projectId }, active: ["script-library", "script-editor", "storyboard-editor"].includes(String(route.name)) },
  ...(props.shotId ? [{ label: "镜头规范", name: "shot-spec", params: { projectId: props.projectId, shotId: props.shotId }, active: route.name === "shot-spec" }] : []),
  { label: "视觉连续性审核", name: "visual-review", params: { projectId: props.projectId }, active: route.name === "visual-review" },
  { label: "用量与预算", name: "project-usage", params: { projectId: props.projectId }, active: route.name === "project-usage" },
  { label: "服务商设置", name: "project-provider-settings", params: { projectId: props.projectId }, active: route.name === "project-provider-settings" },
]);
</script>

<template>
  <nav class="project-workspace-nav" :class="{ 'project-workspace-nav--legacy': !embedded }" aria-label="项目级导航">
    <button v-for="item in items" :key="item.name" :class="{ active: item.active }" @click="router.push({ name: item.name, params: item.params })">{{ item.label }}</button>
  </nav>
</template>

<style scoped>
.project-workspace-nav { display: grid; gap: 6px; }
.project-workspace-nav button { border: 0; background: transparent; color: var(--muted); border-radius: 8px; padding: 11px 12px; text-align: left; cursor: pointer; white-space: nowrap; }
.project-workspace-nav button:hover, .project-workspace-nav button.active { color: var(--primary); background: #edf3ff; font-weight: 700; }
.project-workspace-nav--legacy { position: fixed; z-index: 10; left: max(18px, calc((100vw - 1600px) / 2 + 18px)); top: 28px; width: 205px; max-height: calc(100vh - 56px); overflow: auto; padding: 14px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow); }
@media (max-width: 900px) { .project-workspace-nav--legacy { position: static; width: auto; max-height: none; display: flex; overflow-x: auto; margin-bottom: 16px; } .project-workspace-nav--legacy button { flex: 0 0 auto; } }
</style>
