<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

const props = defineProps<{ projectId: number; shotId?: number }>();
const route = useRoute();
const router = useRouter();
const items = computed(() => [
  { label: "项目工作台", path: `/projects/${props.projectId}`, active: route.name === "project-detail" },
  { label: "连续性资料库", path: `/projects/${props.projectId}/library`, active: route.name === "project-library" },
  { label: "脚本与分镜", path: `/projects/${props.projectId}/scripts`, active: ["script-library", "script-editor", "storyboard-editor"].includes(String(route.name)) },
  ...(props.shotId ? [{ label: "镜头规范", path: `/projects/${props.projectId}/shot/${props.shotId}/spec`, active: route.name === "shot-spec" }] : []),
  { label: "视觉连续性审核", path: `/projects/${props.projectId}/visual-review`, active: route.name === "visual-review" },
  { label: "用量与预算", path: `/projects/${props.projectId}/usage`, active: route.name === "project-usage" },
  { label: "服务商设置", path: "/settings/providers", active: route.name === "provider-settings" },
]);
</script>

<template><aside class="project-workspace-nav" aria-label="项目级导航"><strong>项目工作台</strong><button v-for="item in items" :key="item.path" :class="{active:item.active}" @click="router.push(item.path)">{{item.label}}</button></aside></template>

<style scoped>
.project-workspace-nav{position:fixed;z-index:10;left:max(18px,calc((100vw - 1600px)/2 + 18px));top:28px;width:205px;max-height:calc(100vh - 56px);overflow:auto;padding:14px;background:var(--surface,var(--el-bg-color));border:1px solid var(--border,var(--el-border-color));border-radius:12px;box-shadow:var(--shadow,0 8px 24px rgb(0 0 0/.08));display:grid;gap:6px}strong{padding:8px 10px}button{border:0;background:transparent;color:var(--muted,var(--el-text-color-secondary));border-radius:8px;padding:10px;text-align:left;cursor:pointer}button:hover,button.active{color:var(--primary,var(--el-color-primary));background:#edf3ff;font-weight:700}@media(max-width:900px){.project-workspace-nav{position:static;width:auto;max-height:none;display:flex;overflow-x:auto;margin-bottom:16px}.project-workspace-nav strong{display:none}.project-workspace-nav button{flex:0 0 auto}}
</style>
