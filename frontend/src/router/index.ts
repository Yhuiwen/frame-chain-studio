import { createRouter, createWebHistory } from "vue-router";

import ProjectDetailView from "@/views/ProjectDetailView.vue";
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

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "projects", component: ProjectListView },
    { path: "/projects/:id", name: "project-detail", component: ProjectDetailView },
    { path: "/projects/:projectId/library", name: "project-library", component: ProjectLibraryView },
    { path: "/projects/:projectId/usage", name: "project-usage", component: ProjectUsageView },
    { path: "/visual-review", redirect: "/projects/22/visual-review" },
    { path: "/projects/:projectId/visual-review", name: "visual-review", component: VisualContinuityReview },
    { path: "/settings/providers", name: "provider-settings", component: ProviderSettingsView },
    { path: "/projects/:projectId/scripts", name: "script-library", component: ScriptLibraryView },
    { path: "/projects/:projectId/scripts/:scriptId", name: "script-editor", component: ScriptEditorView },
    { path: "/projects/:projectId/storyboards/:storyboardId", name: "storyboard-editor", component: StoryboardEditorView },
    { path: "/projects/:projectId/shot/:shotId/spec", name: "shot-spec", component: ShotSpecView },
    { path: "/tasks", name: "tasks", component: TasksView },
  ],
});
