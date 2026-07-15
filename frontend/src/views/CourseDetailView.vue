<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteMaterial,
  getCourse,
  knowledgeSummaryStream,
  listMaterials,
  materialDownloadUrl,
  searchMaterialContent,
  uploadMaterial,
} from '../api'
import { renderMarkdown } from '../utils/markdown'

const route = useRoute()
const router = useRouter()
const courseId = Number(route.params.id)

const course = ref(null)
const materials = ref([])
const filter = reactive({ mtype: '', keyword: '' })
const uploadForm = reactive({ mtype: 'courseware', description: '' })
const uploadFiles = ref([])
const uploading = ref(false)
const uploadingIndex = ref(0)
const uploadingFilename = ref('')
const searchQuery = ref('')
const searchHits = ref([])
const summary = ref('')
const summarySources = ref([])
const summaryMode = ref('')
const summarizing = ref(false)
const summaryElapsed = ref(0)
const summaryProgress = reactive({ completed: 0, total: 0, materials: 0, fragments: 0 })
let summaryTimer = null
const sourceMaterialId = computed(() => Number(route.query.material_id) || null)
const sourceCitationIndex = computed(() => route.query.citation || '')
const sourceMaterial = computed(() =>
  materials.value.find((material) => material.id === sourceMaterialId.value),
)

const typeLabels = {
  courseware: '课件',
  notes: '教材笔记',
  assignment: '作业要求',
  lab: '实验指导',
  other: '其他',
}
const maxUploadBytes = 50 * 1024 * 1024
const maxUploadCount = 10
const summaryHtml = computed(() => renderMarkdown(summary.value))
const summaryMaterialCount = computed(
  () => new Set(summarySources.value.map((source) => source.material_id)).size,
)
const summaryPercent = computed(() =>
  summaryProgress.total
    ? Math.round((summaryProgress.completed / summaryProgress.total) * 100)
    : 0,
)
const summaryButtonText = computed(() => {
  if (!summarizing.value) return '生成知识点提纲'
  if (!summaryProgress.total) return '正在读取并排序资料…'
  return `正在整理 ${summaryProgress.completed}/${summaryProgress.total} 批`
})
const selectedFileSize = computed(() =>
  uploadFiles.value.reduce((total, file) => total + (file.raw?.size || file.size || 0), 0),
)
const uploadButtonText = computed(() => {
  if (!uploading.value) {
    return uploadFiles.value.length ? `上传 ${uploadFiles.value.length} 个文件` : '开始上传'
  }
  return `正在上传 ${uploadingIndex.value + 1}/${uploadFiles.value.length}`
})

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function refreshMaterials() {
  const params = {}
  if (filter.mtype) params.mtype = filter.mtype
  if (filter.keyword) params.keyword = filter.keyword
  const { data } = await listMaterials(courseId, params)
  materials.value = data
}

onMounted(async () => {
  const { data } = await getCourse(courseId)
  course.value = data
  await refreshMaterials()
  if (sourceMaterialId.value) {
    await nextTick()
    document.querySelector('.source-material-row')?.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
    })
  }
})

function materialRowClassName({ row }) {
  return row.id === sourceMaterialId.value ? 'source-material-row' : ''
}

function removeUploadFile(uid) {
  uploadFiles.value = uploadFiles.value.filter((file) => file.uid !== uid)
}

function onFileChange(file, files) {
  const raw = file.raw
  if (!raw) return
  if (!raw.size) {
    ElMessage.warning(`「${file.name}」是空文件，已忽略`)
    removeUploadFile(file.uid)
    return
  }
  if (raw.size > maxUploadBytes) {
    ElMessage.error(`「${file.name}」超过 50MB，无法上传`)
    removeUploadFile(file.uid)
    return
  }
  const duplicate = files.some(
    (item) =>
      item.uid !== file.uid &&
      item.name === file.name &&
      (item.raw?.size || item.size) === raw.size &&
      item.raw?.lastModified === raw.lastModified,
  )
  if (duplicate) {
    ElMessage.info(`「${file.name}」已在上传列表中`)
    removeUploadFile(file.uid)
  }
}

function onUploadExceed() {
  ElMessage.warning(`一次最多添加 ${maxUploadCount} 个文件，请分批上传`)
}

async function submitUpload() {
  const pendingFiles = uploadFiles.value.filter((file) => file.raw)
  if (!pendingFiles.length) {
    ElMessage.warning('请拖入文件或点击上传区域选择文件')
    return
  }
  uploading.value = true
  uploadingIndex.value = 0
  const succeeded = new Set()
  const failed = []
  try {
    for (const [index, file] of pendingFiles.entries()) {
      uploadingIndex.value = index
      uploadingFilename.value = file.name
      const formData = new FormData()
      formData.append('file', file.raw)
      formData.append('mtype', uploadForm.mtype)
      formData.append('description', uploadForm.description)
      try {
        await uploadMaterial(courseId, formData)
        succeeded.add(file.uid)
      } catch {
        failed.push(file.name)
      }
    }
    uploadFiles.value = uploadFiles.value.filter((file) => !succeeded.has(file.uid))
    if (succeeded.size) {
      uploadForm.description = ''
      await refreshMaterials()
    }
    if (!failed.length) {
      ElMessage.success(`已上传 ${succeeded.size} 个文件，可解析内容已加入 Agent 资料库`)
    } else if (succeeded.size) {
      ElMessage.warning(`成功 ${succeeded.size} 个，失败 ${failed.length} 个；失败文件已保留，可重试`)
    } else {
      ElMessage.error('文件上传失败，已保留上传列表，请稍后重试')
    }
  } finally {
    uploading.value = false
    uploadingFilename.value = ''
    uploadingIndex.value = 0
  }
}

async function removeMaterial(m) {
  await ElMessageBox.confirm(`确定删除资料「${m.filename}」？`, '删除确认', {
    type: 'warning',
  })
  await deleteMaterial(m.id)
  ElMessage.success('已删除')
  await refreshMaterials()
}

async function doSearch() {
  if (!searchQuery.value.trim()) return
  const { data } = await searchMaterialContent(courseId, searchQuery.value)
  searchHits.value = data
  if (!data.length) ElMessage.info('未检索到相关内容')
}

async function generateSummary() {
  summarizing.value = true
  summary.value = ''
  summarySources.value = []
  summaryMode.value = ''
  summaryElapsed.value = 0
  Object.assign(summaryProgress, { completed: 0, total: 0, materials: 0, fragments: 0 })
  summaryTimer = window.setInterval(() => {
    summaryElapsed.value += 1
  }, 1000)
  try {
    await knowledgeSummaryStream(courseId, {
      onMeta(data) {
        Object.assign(summaryProgress, {
          total: data.total || 0,
          materials: data.materials || 0,
          fragments: data.fragments || 0,
        })
      },
      onProgress(data) {
        summaryProgress.completed = data.completed || 0
      },
      onDone(data) {
        summary.value = data.summary
        summarySources.value = data.sources || []
        summaryMode.value = data.agent_mode
        summaryProgress.completed = summaryProgress.total
      },
    })
  } catch (error) {
    ElMessage.error(error.message || '知识点整理失败，请稍后重试')
  } finally {
    window.clearInterval(summaryTimer)
    summaryTimer = null
    summarizing.value = false
  }
}

function download(m) {
  const token = localStorage.getItem('token')
  fetch(materialDownloadUrl(m.id), { headers: { Authorization: `Bearer ${token}` } })
    .then((r) => r.blob())
    .then((blob) => {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = m.filename
      a.click()
      URL.revokeObjectURL(url)
    })
}
</script>

<template>
  <div v-if="course">
    <el-page-header @back="router.push('/courses')">
      <template #content>
        <span class="title">{{ course.name }}</span>
        <el-tag v-if="course.semester" size="small" class="ml">{{ course.semester }}</el-tag>
      </template>
      <template #extra>
        <el-button type="primary" @click="router.push(`/courses/${courseId}/chat`)">
          <el-icon><ChatDotRound /></el-icon>Agent 问答
        </el-button>
      </template>
    </el-page-header>

    <el-tabs class="tabs">
      <el-tab-pane label="资料管理">
        <el-card class="block">
          <template #header>上传资料</template>
          <div class="upload-panel">
            <el-upload
              v-model:file-list="uploadFiles"
              class="material-uploader"
              drag
              multiple
              :auto-upload="false"
              :limit="maxUploadCount"
              :disabled="uploading"
              :on-change="onFileChange"
              :on-exceed="onUploadExceed"
            >
              <el-icon class="upload-icon"><UploadFilled /></el-icon>
              <div class="el-upload__text">
                将课程资料拖到此处，或 <em>点击选择文件</em>
              </div>
              <template #tip>
                <div class="el-upload__tip">
                  单个文件不超过 50MB，一次最多 10 个；PDF、Word、PPT、Markdown、文本和代码文件可提取内容供 Agent 检索。
                </div>
              </template>
            </el-upload>
            <div class="upload-settings">
              <el-select v-model="uploadForm.mtype" :disabled="uploading" aria-label="资料类型">
                <el-option
                  v-for="(label, value) in typeLabels"
                  :key="value"
                  :label="label"
                  :value="value"
                />
              </el-select>
              <el-input
                v-model="uploadForm.description"
                :disabled="uploading"
                placeholder="资料说明（选填，将应用到本批文件）"
                maxlength="2000"
                show-word-limit
              />
              <el-button
                type="primary"
                :loading="uploading"
                :disabled="!uploadFiles.length"
                @click="submitUpload"
              >
                {{ uploadButtonText }}
              </el-button>
            </div>
            <div v-if="uploadFiles.length" class="upload-queue-summary">
              <span>待上传 {{ uploadFiles.length }} 个文件，共 {{ formatFileSize(selectedFileSize) }}</span>
              <span v-if="uploadingFilename" class="upload-current">当前：{{ uploadingFilename }}</span>
              <el-button v-else link type="danger" @click="uploadFiles = []">清空列表</el-button>
            </div>
          </div>
        </el-card>

        <el-card class="block">
          <template #header>
            <div class="filter-row">
              <span>资料列表</span>
              <div class="filters">
                <el-select v-model="filter.mtype" clearable placeholder="全部类型" style="width: 130px" @change="refreshMaterials">
                  <el-option v-for="(label, value) in typeLabels" :key="value" :label="label" :value="value" />
                </el-select>
                <el-input v-model="filter.keyword" placeholder="按文件名/说明筛选" clearable style="width: 200px" @change="refreshMaterials" />
              </div>
            </div>
          </template>
          <el-alert
            v-if="sourceMaterial"
            type="success"
            :closable="false"
            show-icon
            class="source-alert"
            :title="`已从 Agent 回答的引用${sourceCitationIndex ? ` [${sourceCitationIndex}]` : ''}跳转到《${sourceMaterial.filename}》`"
            description="下方高亮行即为回答的来源资料，可下载原文或继续检索正文片段。"
          />
          <el-table
            :data="materials"
            empty-text="暂无资料"
            :row-class-name="materialRowClassName"
          >
            <el-table-column prop="filename" label="文件名" min-width="180" />
            <el-table-column label="类型" width="110">
              <template #default="{ row }">
                <el-tag size="small">{{ typeLabels[row.mtype] || row.mtype }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="description" label="说明" min-width="140" show-overflow-tooltip />
            <el-table-column label="大小" width="100">
              <template #default="{ row }">{{ (row.size_bytes / 1024).toFixed(1) }} KB</template>
            </el-table-column>
            <el-table-column label="操作" width="160">
              <template #default="{ row }">
                <el-button size="small" link type="primary" @click="download(row)">下载</el-button>
                <el-button size="small" link type="danger" @click="removeMaterial(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card class="block">
          <template #header>资料内容检索</template>
          <div class="upload-row">
            <el-input
              v-model="searchQuery"
              placeholder="输入关键词，在资料正文中检索相关片段"
              style="width: 320px"
              @keyup.enter="doSearch"
            />
            <el-button type="primary" @click="doSearch">检索</el-button>
          </div>
          <div v-for="hit in searchHits" :key="hit.chunk_id" class="hit">
            <div class="hit-source">《{{ hit.material_name }}》 · 匹配度 {{ hit.score }}</div>
            <div class="hit-text">{{ hit.excerpt }}…</div>
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="知识点整理">
        <el-card class="block">
          <template #header>
            <div class="filter-row">
              <span>复习提纲（根据课程资料自动提取重点知识点）</span>
              <el-button type="primary" :loading="summarizing" @click="generateSummary">
                {{ summaryButtonText }}
              </el-button>
            </div>
          </template>
          <div v-if="summarizing" class="summary-progress">
            <div class="summary-progress-title">
              <span>
                {{ summaryProgress.total
                  ? `正在并行整理 ${summaryProgress.materials} 份资料、${summaryProgress.fragments} 个片段`
                  : '正在读取资料并识别章节顺序' }}
              </span>
              <span>{{ summaryElapsed }} 秒</span>
            </div>
            <el-progress
              v-if="summaryProgress.total"
              :percentage="summaryPercent"
              :stroke-width="10"
            />
            <div class="summary-progress-tip">
              {{ summaryProgress.total
                ? `已完成 ${summaryProgress.completed}/${summaryProgress.total} 批，结果完成后将按章节顺序统一展示。`
                : '正在准备分批任务，请稍候…' }}
            </div>
          </div>
          <el-alert
            v-if="summaryMode === 'fallback'"
            type="warning"
            :closable="false"
            class="block"
            title="当前为离线模式（未配置大模型 API Key），仅展示资料片段目录"
          />
          <el-alert
            v-else-if="summary && summarySources.length"
            type="success"
            :closable="false"
            class="block"
            :title="`已按章节顺序整理 ${summaryMaterialCount} 份资料`"
            :description="`本次覆盖全部 ${summarySources.length} 个可解析内容片段，并按资料章节号、文件名和原文顺序生成。`"
          />
          <div v-if="summary" class="markdown" v-html="summaryHtml" />
          <el-empty v-else-if="!summarizing" description="点击右上角按钮生成知识点提纲" />
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.title {
  font-size: 18px;
  font-weight: 600;
}
.ml {
  margin-left: 8px;
}
.tabs {
  margin-top: 16px;
}
.block {
  margin-bottom: 16px;
}
.upload-row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  flex-wrap: wrap;
}
.upload-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.material-uploader {
  width: 100%;
}
.material-uploader :deep(.el-upload),
.material-uploader :deep(.el-upload-dragger) {
  width: 100%;
}
.material-uploader :deep(.el-upload-dragger) {
  box-sizing: border-box;
  padding: 28px 20px;
  border-radius: 10px;
  background: #f8fbff;
  transition: border-color 0.2s, background-color 0.2s;
}
.material-uploader :deep(.el-upload-dragger:hover) {
  border-color: #409eff;
  background: #f0f7ff;
}
.material-uploader :deep(.el-upload-list) {
  margin-top: 10px;
}
.upload-icon {
  margin-bottom: 10px;
  font-size: 46px;
  color: #409eff;
}
.upload-settings {
  display: grid;
  grid-template-columns: 160px minmax(260px, 1fr) auto;
  gap: 12px;
  align-items: start;
}
.upload-queue-summary {
  display: flex;
  min-height: 24px;
  align-items: center;
  justify-content: space-between;
  color: #606266;
  font-size: 13px;
}
.upload-current {
  max-width: 50%;
  overflow: hidden;
  color: #409eff;
  text-overflow: ellipsis;
  white-space: nowrap;
}
@media (max-width: 800px) {
  .upload-settings {
    grid-template-columns: 1fr;
  }
  .upload-settings .el-button {
    width: 100%;
  }
}
.filter-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.filters {
  display: flex;
  gap: 8px;
}
.source-alert {
  margin-bottom: 12px;
}
:deep(.source-material-row > td.el-table__cell) {
  background: #ecf5ff !important;
}
:deep(.source-material-row td:first-child) {
  box-shadow: inset 3px 0 #409eff;
}
.hit {
  padding: 10px 0;
  border-bottom: 1px dashed #e4e7ed;
}
.hit-source {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.hit-text {
  font-size: 13px;
  color: #303133;
}
.summary-progress {
  padding: 16px 18px;
  margin-bottom: 16px;
  border: 1px solid #b3d8ff;
  border-radius: 8px;
  background: #f0f7ff;
}
.summary-progress-title {
  display: flex;
  justify-content: space-between;
  margin-bottom: 12px;
  color: #1f4e79;
  font-size: 14px;
  font-weight: 600;
}
.summary-progress-tip {
  margin-top: 8px;
  color: #606266;
  font-size: 12px;
}
.markdown :deep(h1),
.markdown :deep(h2),
.markdown :deep(h3) {
  margin: 12px 0 6px;
}
.markdown :deep(p),
.markdown :deep(li) {
  line-height: 1.7;
  font-size: 14px;
}
</style>
