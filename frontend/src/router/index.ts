import { createRouter, createWebHistory } from "vue-router";

import ProjectDetailView from "@/views/ProjectDetailView.vue";
import ProjectWorkspaceLayout from "@/components/ProjectWorkspaceLayout.vue";
import ProjectLibraryView from "@/views/ProjectLibraryView.vue";
import ProjectListView from "@/views/ProjectListView.vue";
import ProjectUsageView from "@/views/ProjectUsageView.vue";
import ProviderSettingsView from "@/views/ProviderSettingsView.vue";
import ScriptEditorView from "@/views/ScriptEditorView.vue";
import ScriptLibraryView from "@/views/ScriptLibraryView.vue";
import ShotSpecView from "@/views/ShotSpecView.vue";
import StoryboardEditorView from "@/views/StoryboardEditorView.vue";
import TasksView from "@/views/TasksView.vue";
import VisualContinuityReview from "@/views/VisualContinuityReview.vue";
import VisualRegenerationView from "@/views/VisualRegenerationView.vue";
import NotFoundView from "@/views/NotFoundView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "projects", component: ProjectListView },
    { path: "/visual-review", redirect: "/projects/22/visual-review" },
    {
      path: "/settings/providers",
      name: "provider-settings",
      component: ProviderSettingsView,
    },
    {
      path: "/projects/:projectId",
      component: ProjectWorkspaceLayout,
      children: [
        {
          path: "",
          name: "project-workbench",
          component: ProjectDetailView,
          meta: { workspaceTitle: "项目工作台" },
        },
        {
          path: "library",
          name: "project-library",
          component: ProjectLibraryView,
          meta: { workspaceTitle: "连续性资料库" },
        },
        {
          path: "usage",
          name: "project-usage",
          component: ProjectUsageView,
          meta: { workspaceTitle: "用量与预算" },
        },
        {
          path: "visual-review",
          name: "project-visual-review",
          component: VisualContinuityReview,
          meta: { workspaceTitle: "视觉连续性审核" },
        },
        {
          path: "visual-regeneration",
          name: "visual-regeneration",
          component: VisualRegenerationView,
          meta: { workspaceTitle: "视觉再生成计划" },
        },
        {
          path: "settings/providers",
          name: "project-provider-settings",
          component: ProviderSettingsView,
          meta: { workspaceTitle: "服务商设置" },
        },
        {
          path: "scripts",
          name: "project-scripts",
          component: ScriptLibraryView,
          meta: { workspaceTitle: "脚本与分镜" },
        },
        {
          path: "scripts/:scriptId",
          name: "script-editor",
          component: ScriptEditorView,
          meta: { workspaceTitle: "脚本解析" },
        },
        {
          path: "storyboards/:storyboardId",
          name: "storyboard-editor",
          component: StoryboardEditorView,
          meta: { workspaceTitle: "分镜编辑" },
        },
        {
          path: "shot/:shotId/spec",
          name: "project-shot-spec",
          component: ShotSpecView,
          meta: { workspaceTitle: "镜头规范" },
        },
      ],
    },
    { path: "/tasks", name: "tasks", component: TasksView },
    { path: "/:pathMatch(.*)*", name: "not-found", component: NotFoundView },
  ],
});
