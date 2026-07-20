import { createRouter, createWebHistory } from "vue-router";

import ProjectDetailView from "@/views/ProjectDetailView.vue";
import ProjectListView from "@/views/ProjectListView.vue";
import TasksView from "@/views/TasksView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "projects", component: ProjectListView },
    { path: "/projects/:id", name: "project-detail", component: ProjectDetailView },
    { path: "/tasks", name: "tasks", component: TasksView },
  ],
});
