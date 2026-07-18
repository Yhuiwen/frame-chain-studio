<script setup lang="ts">
import { CaretRight, Check, Close, Picture, Plus, Refresh, VideoPlay } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { api, type Shot } from "@/api/client";
import { useStudioStore } from "@/stores/studio";

const route = useRoute();
const store = useStudioStore();
const draggedShotId = ref<number | null>(null);
const projectId = computed(() => Number(route.params.id));
const selected = computed(() => store.selectedShot);
const keyframes = computed(() => (selected.value ? store.assetsByShot(selected.value.id, "KEYFRAME") : []));
const videos = computed(() => (selected.value ? store.assetsByShot(selected.value.id, "VIDEO") : []));
const tailFrames = computed(() => (selected.value ? store.assetsByShot(selected.value.id, "TAIL_FRAME") : []));

onMounted(() => {
  void store.loadProject(projectId.value);
});

function statusType(status: Shot["status"]) {
  if (status.includes("APPROVED") || status === "COMPLETED") return "success";
  if (status.includes("REVIEW")) return "warning";
  if (status.includes("GENERATING")) return "primary";
  return "info";
}

async function guarded(action: () => Promise<unknown>) {
  try {
    await action();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "操作失败");
  }
}

async function dropOn(target: Shot) {
  if (!store.current || draggedShotId.value === null || draggedShotId.value === target.id) return;
  const shots = [...store.current.shots];
  const from = shots.findIndex((shot) => shot.id === draggedShotId.value);
  const to = shots.findIndex((shot) => shot.id === target.id);
  const [shot] = shots.splice(from, 1);
  shots.splice(to, 0, shot);
  draggedShotId.value = null;
  await guarded(() => store.reorder(store.current?.id ?? projectId.value, shots));
}
</script>

<template>
  <main class="workspace" v-loading="store.loading">
    <section class="workspace-header">
      <div>
        <h1>{{ store.current?.name }}</h1>
        <p>{{ store.current?.description || "Mock 后端阶段：所有生成资产和状态变化都会持久化。" }}</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" @click="store.loadProject(projectId)">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="guarded(() => store.createShot(projectId))">添加 Shot</el-button>
      </div>
    </section>

    <section class="layout">
      <aside class="timeline">
        <button
          v-for="shot in store.current?.shots"
          :key="shot.id"
          class="timeline-item"
          :class="{ active: shot.id === selected?.id }"
          draggable="true"
          @dragstart="draggedShotId = shot.id"
          @dragover.prevent
          @drop="dropOn(shot)"
          @click="store.selectShot(shot.id)"
        >
          <span class="order">{{ shot.sort_order + 1 }}</span>
          <span class="shot-title">{{ shot.title }}</span>
          <el-tag size="small" :type="statusType(shot.status)">{{ shot.status }}</el-tag>
        </button>
      </aside>

      <section v-if="selected" class="review-grid">
        <div class="editor-panel">
          <div class="panel-title">
            <h2>{{ selected.title }}</h2>
            <el-tag :type="statusType(selected.status)">{{ selected.status }}</el-tag>
          </div>
          <el-form label-position="top">
            <el-form-item label="标题">
              <el-input :model-value="selected.title" @change="store.updateSelectedShot({ title: String($event) })" />
            </el-form-item>
            <el-form-item label="描述">
              <el-input
                :model-value="selected.description"
                type="textarea"
                :rows="2"
                @change="store.updateSelectedShot({ description: String($event) })"
              />
            </el-form-item>
            <el-form-item label="时长">
              <el-input-number
                :model-value="selected.duration_seconds"
                :min="0.1"
                :max="60"
                @change="store.updateSelectedShot({ duration_seconds: Number($event) })"
              />
            </el-form-item>
            <el-form-item label="提示词">
              <el-input
                :model-value="selected.prompt"
                type="textarea"
                :rows="4"
                @change="store.updateSelectedShot({ prompt: String($event) })"
              />
            </el-form-item>
            <el-form-item label="负面约束">
              <el-input
                :model-value="selected.negative_prompt"
                type="textarea"
                :rows="3"
                @change="store.updateSelectedShot({ negative_prompt: String($event) })"
              />
            </el-form-item>
          </el-form>
        </div>

        <div class="review-panel">
          <div class="panel-title">
            <h2>关键帧审核</h2>
            <el-button
              type="primary"
              :icon="Picture"
              :disabled="selected.status !== 'DRAFT'"
              @click="guarded(() => store.runAction(api.generateKeyframe))"
            >
              生成关键帧
            </el-button>
          </div>
          <div class="asset-strip">
            <img v-for="asset in keyframes" :key="asset.id" :src="`/api/media/${asset.id}`" :alt="asset.type" />
            <el-empty v-if="!keyframes.length" description="暂无关键帧" />
          </div>
          <div class="button-row">
            <el-button
              type="success"
              :icon="Check"
              :disabled="selected.status !== 'KEYFRAME_REVIEW'"
              @click="guarded(() => store.runAction(api.approveKeyframe))"
            >
              批准
            </el-button>
            <el-button
              :icon="Close"
              :disabled="selected.status !== 'KEYFRAME_REVIEW'"
              @click="guarded(() => store.runAction(api.rejectKeyframe))"
            >
              拒绝
            </el-button>
          </div>
        </div>

        <div class="review-panel">
          <div class="panel-title">
            <h2>视频审核</h2>
            <el-button
              type="primary"
              :icon="VideoPlay"
              :disabled="selected.status !== 'KEYFRAME_APPROVED'"
              @click="guarded(() => store.runAction(api.generateVideo))"
            >
              生成视频
            </el-button>
          </div>
          <div class="asset-strip">
            <video v-for="asset in videos" :key="asset.id" controls :src="`/api/media/${asset.id}`" />
            <el-empty v-if="!videos.length" description="暂无视频" />
          </div>
          <div class="button-row">
            <el-button
              type="success"
              :icon="Check"
              :disabled="selected.status !== 'VIDEO_REVIEW'"
              @click="guarded(() => store.runAction(api.approveVideo))"
            >
              批准并锁尾帧
            </el-button>
            <el-button
              :icon="Close"
              :disabled="selected.status !== 'VIDEO_REVIEW'"
              @click="guarded(() => store.runAction(api.rejectVideo))"
            >
              拒绝
            </el-button>
          </div>
          <div class="tail-row">
            <span>尾帧</span>
            <img v-for="asset in tailFrames" :key="asset.id" :src="`/api/media/${asset.id}`" :alt="asset.type" />
          </div>
        </div>

        <div class="log-panel">
          <div class="panel-title">
            <h2>任务日志</h2>
            <el-button :icon="CaretRight" text @click="store.loadProject(projectId)">同步</el-button>
          </div>
          <el-timeline>
            <el-timeline-item v-for="log in store.logsForSelected" :key="log.id" :timestamp="log.created_at">
              <strong>{{ log.level }}</strong>
              {{ log.message }}
            </el-timeline-item>
          </el-timeline>
        </div>
      </section>
    </section>
  </main>
</template>
