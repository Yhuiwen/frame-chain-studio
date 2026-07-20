import { createRouter, createWebHistory } from "vue-router";

import ProjectDetailView from "@/views/ProjectDetailView.vue";
import ProjectLibraryView from "@/views/ProjectLibraryView.vue";
import ProjectListView from "@/views/ProjectListView.vue";
import ShotSpecView from "@/views/ShotSpecView.vue";
import TasksView from "@/views/TasksView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "projects", component: ProjectListView },
    { path: "/projects/:id", name: "project-detail", component: ProjectDetailView },
    { path: "/projects/:projectId/library", name: "project-library", component: ProjectLibraryView },
    { path: "/projects/:projectId/shot/:shotId/spec", name: "shot-spec", component: ShotSpecView },
    { path: "/tasks", name: "tasks", component: TasksView },
  ],
});
