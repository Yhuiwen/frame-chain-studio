<script setup lang="ts">
import { Plus } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { onMounted, reactive } from "vue";
import { useRouter } from "vue-router";

import { useStudioStore } from "@/stores/studio";

const store = useStudioStore();
const router = useRouter();
const form = reactive({ name: "新长视频项目", description: "" });

onMounted(() => {
  void store.loadProjects();
});

async function createProject() {
  try {
    const project = await store.createProject(form.name, form.description);
    await router.push(`/projects/${project.id}`);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "创建失败");
  }
}
</script>

<template>
  <main class="page">
    <section class="toolbar">
      <div>
        <h1>Frame Chain Studio</h1>
        <p>从关键帧审核、镜头生成到尾帧衔接，集中管理长视频分镜工作流。</p>
      </div>
      <el-form class="create-form" :inline="true" @submit.prevent="createProject">
        <el-input v-model="form.name" placeholder="项目名称" />
        <el-input v-model="form.description" placeholder="项目描述（可选）" />
        <el-button native-type="button" type="primary" :icon="Plus" @click="createProject">创建项目</el-button>
      </el-form>
    </section>

    <el-table v-loading="store.loading" :data="store.projects" stripe class="project-table">
      <el-table-column prop="name" label="项目" min-width="220" />
      <el-table-column prop="description" label="描述" min-width="320" show-overflow-tooltip />
      <el-table-column prop="updated_at" label="更新时间" width="220" />
      <el-table-column width="120" align="right">
        <template #default="{ row }">
          <el-button native-type="button" text type="primary" @click="router.push(`/projects/${row.id}`)">打开</el-button>
        </template>
      </el-table-column>
    </el-table>
  </main>
</template>
