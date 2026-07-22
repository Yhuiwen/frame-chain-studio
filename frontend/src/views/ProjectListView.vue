<script setup lang="ts">
import { MoreFilled, Plus, Search } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { api, ApiError, type Project } from "@/api/client";

const router = useRouter();
const projects = ref<Project[]>([]); const loading = ref(false); const submitting = ref(false);
const search = ref(""); const filter = ref<"active" | "archived">("active");
const form = reactive({ name: "", description: "" }); const nameError = ref("");
const shown = computed(() => projects.value.filter(item => `${item.name} ${item.description}`.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())));

onMounted(load);
async function load() { loading.value = true; try { projects.value = await api.listProjects(filter.value === "archived"); } finally { loading.value = false; } }
async function createProject() {
  nameError.value = ""; if (!form.name.trim()) { nameError.value = "请输入项目名称。"; return; }
  submitting.value = true;
  try { const item = await api.createProject(form); form.name = ""; form.description = ""; await router.push(`/projects/${item.id}`); }
  catch (e) { if (e instanceof ApiError && e.code === "PROJECT_NAME_CONFLICT") nameError.value = e.message.split(" (")[0]; else ElMessage.error(e instanceof Error ? e.message : "创建失败"); }
  finally { submitting.value = false; }
}
async function rename(item: Project) { try { const value = await ElMessageBox.prompt("输入新的项目名称", "重命名项目", { inputValue: item.name, inputPattern: /\S/, inputErrorMessage: "请输入项目名称" }); await api.updateProject(item.id, { name: value.value }); await load(); } catch { /* cancelled */ } }
async function archive(item: Project) { await api.archiveProject(item.id); ElMessage.success("项目已移除，可在已移除项目中恢复。"); await load(); }
async function restore(item: Project) { await api.restoreProject(item.id); ElMessage.success("项目已恢复。"); await load(); }
async function removeForever(item: Project) { try { const result = await ElMessageBox.prompt("该操作会永久删除项目、镜头、记录和本地媒体文件，且无法恢复。请输入完整项目名称：", "永久删除项目", { confirmButtonText: "我理解并永久删除", inputPattern: new RegExp(`^${item.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`), inputErrorMessage: "项目名称不匹配", type: "error" }); await api.permanentlyDeleteProject(item.id, result.value); ElMessage.success("项目已永久删除。"); await load(); } catch { /* cancelled */ } }
function formatDate(value: string) { return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
</script>

<template><main class="projects-page">
  <header class="hero"><div><p class="brand">帧链工作室 · Frame Chain Studio</p><h1>项目</h1><p>管理长视频项目、镜头和生成流程</p></div>
    <el-form class="create" @submit.prevent="createProject"><el-form-item :error="nameError"><el-input v-model="form.name" maxlength="160" show-word-limit placeholder="项目名称" /></el-form-item><el-input v-model="form.description" maxlength="1000" placeholder="项目描述（可选）" /><el-button type="primary" :icon="Plus" :disabled="!form.name.trim()" :loading="submitting" @click="createProject">新建项目</el-button></el-form>
  </header>
  <section class="controls"><el-input v-model="search" :prefix-icon="Search" clearable placeholder="搜索项目" /><el-radio-group v-model="filter" @change="load"><el-radio-button value="active">全部</el-radio-button><el-radio-button value="archived">已移除</el-radio-button></el-radio-group><span>共 {{ projects.length }} 个，显示 {{ shown.length }} 个</span></section>
  <el-empty v-if="!loading && !shown.length" :description="filter === 'archived' ? '暂无已移除项目' : '暂无项目，创建第一个项目开始工作'" />
  <section v-loading="loading" class="grid"><article v-for="item in shown" :key="item.id" class="card"><div class="card-head"><h2>{{ item.name }}</h2><el-dropdown trigger="click"><el-button text :icon="MoreFilled" aria-label="更多操作" /><template #dropdown><el-dropdown-menu><el-dropdown-item v-if="!item.archived_at" @click="rename(item)">重命名</el-dropdown-item><el-dropdown-item v-if="!item.archived_at" @click="archive(item)">移除</el-dropdown-item><el-dropdown-item v-if="item.archived_at" @click="restore(item)">恢复</el-dropdown-item><el-dropdown-item v-if="item.archived_at" divided @click="removeForever(item)">永久删除</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div><p class="description">{{ item.description || "暂无描述" }}</p><footer><span>更新于 {{ formatDate(item.updated_at) }}</span><el-button v-if="!item.archived_at" type="primary" @click="router.push(`/projects/${item.id}`)">打开</el-button></footer></article></section>
</main></template>

<style scoped>.projects-page{padding:clamp(16px,3vw,36px);max-width:1440px;margin:auto}.hero{display:grid;grid-template-columns:minmax(260px,1fr) minmax(420px,1.4fr);gap:28px;align-items:end}.brand{color:var(--el-color-primary);font-weight:700}.hero h1{font-size:34px;margin:8px 0}.create{display:grid;grid-template-columns:1fr 1fr auto;gap:10px;align-items:start}.create :deep(.el-form-item){margin:0}.controls{display:grid;grid-template-columns:minmax(220px,420px) auto 1fr;gap:16px;align-items:center;margin:28px 0}.controls span{text-align:right;color:var(--el-text-color-secondary)}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}.card{border:1px solid var(--el-border-color);border-radius:14px;padding:18px;background:var(--el-bg-color);min-width:0}.card-head,footer{display:flex;justify-content:space-between;align-items:center;gap:10px}.card h2{margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.description{color:var(--el-text-color-secondary);height:3em;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}footer span{font-size:13px;color:var(--el-text-color-secondary)}@media(max-width:760px){.hero,.create,.controls{grid-template-columns:1fr}.controls span{text-align:left}.projects-page{padding:14px}.grid{grid-template-columns:1fr}}</style>
