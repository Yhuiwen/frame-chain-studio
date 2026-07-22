<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
const props = defineProps<{ projectId: number; shotId?: number }>();
const route = useRoute();
const router = useRouter();
const items = computed(() => [
  {
    label: "项目工作台",
    name: "project-workbench",
    params: { projectId: props.projectId },
    active: route.name === "project-workbench",
  },
  {
    label: "连续性资料库",
    name: "project-library",
    params: { projectId: props.projectId },
    active: route.name === "project-library",
  },
  {
    label: "脚本与分镜",
    name: "project-scripts",
    params: { projectId: props.projectId },
    active: ["project-scripts", "script-editor", "storyboard-editor"].includes(
      String(route.name),
    ),
  },
  ...(props.shotId
    ? [
        {
          label: "镜头规范",
          name: "project-shot-spec",
          params: { projectId: props.projectId, shotId: props.shotId },
          active: route.name === "project-shot-spec",
        },
      ]
    : []),
  {
    label: "视觉连续性审核",
    name: "project-visual-review",
    params: { projectId: props.projectId },
    active: ["project-visual-review", "visual-regeneration"].includes(
      String(route.name),
    ),
  },
  {
    label: "用量与预算",
    name: "project-usage",
    params: { projectId: props.projectId },
    active: route.name === "project-usage",
  },
  {
    label: "服务商设置",
    name: "project-provider-settings",
    params: { projectId: props.projectId },
    active: route.name === "project-provider-settings",
  },
]);
</script>
<template>
  <nav class="project-workspace-nav" aria-label="项目级导航">
    <button
      v-for="item in items"
      :key="item.name"
      :class="{ active: item.active }"
      @click="router.push({ name: item.name, params: item.params })"
    >
      {{ item.label }}
    </button>
  </nav>
</template>
<style scoped>
.project-workspace-nav {
  display: grid;
  gap: 6px;
}
.project-workspace-nav button {
  border: 0;
  background: transparent;
  color: var(--muted);
  border-radius: 8px;
  padding: 11px 12px;
  text-align: left;
  cursor: pointer;
  white-space: nowrap;
}
.project-workspace-nav button:hover,
.project-workspace-nav button.active {
  color: var(--primary);
  background: #edf3ff;
  font-weight: 700;
}
</style>
