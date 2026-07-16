<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteMaterial,
  deleteQuiz,
  generateQuiz,
  getCourse,
  getLearningProgress,
  getQuiz,
  knowledgeSummaryStream,
  listMaterials,
  listQuizzes,
  materialDownloadUrl,
  searchMaterialContent,
  submitQuiz,
  uploadMaterial,
} from '../api'
import { renderMarkdown } from '../utils/markdown'

const route = useRoute()
const router = useRouter()
const courseId = Number(route.params.id)

const course = ref(null)
const activeTab = ref('materials')
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
const quizzes = ref([])
const learningProgress = ref(null)
const quizForm = reactive({ stage: '当前学习阶段', focus: '', question_count: 5 })
const generatingQuiz = ref(false)
const activeQuiz = ref(null)
const quizAnswers = ref([])
const quizResult = ref(null)
const submittingQuiz = ref(false)
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
const answeredCount = computed(() =>
  quizAnswers.value.filter((answer) => Number.isInteger(answer)).length,
)
const resultByQuestion = computed(() =>
  Object.fromEntries(
    (quizResult.value?.results || []).map((item) => [item.question_id, item]),
  ),
)

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

async function refreshQuizData() {
  const [{ data: quizData }, { data: progressData }] = await Promise.all([
    listQuizzes(courseId),
    getLearningProgress(courseId),
  ])
  quizzes.value = quizData
  learningProgress.value = progressData
}

onMounted(async () => {
  const { data } = await getCourse(courseId)
  course.value = data
  await Promise.all([refreshMaterials(), refreshQuizData()])
  if (sourceMaterialId.value) {
    await nextTick()
    document.querySelector('.source-material-row')?.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
    })
  }
})

async function createStageQuiz() {
  generatingQuiz.value = true
  try {
    const { data } = await generateQuiz(courseId, quizForm)
    quizzes.value.unshift(data)
    openQuiz(data)
    ElMessage.success('阶段测验已生成，请完成全部题目后提交')
  } finally {
    generatingQuiz.value = false
  }
}

async function openQuiz(quiz) {
  const { data } = quiz.questions?.length ? { data: quiz } : await getQuiz(quiz.id)
  activeQuiz.value = data
  quizAnswers.value = Array(data.question_count).fill(null)
  quizResult.value = null
}

function closeQuiz() {
  activeQuiz.value = null
  quizAnswers.value = []
  quizResult.value = null
}

async function submitActiveQuiz() {
  if (answeredCount.value !== activeQuiz.value.question_count) {
    ElMessage.warning('请完成全部题目后再提交')
    return
  }
  submittingQuiz.value = true
  try {
    const { data } = await submitQuiz(activeQuiz.value.id, quizAnswers.value)
    quizResult.value = data
    ElMessage.success(`测验完成：${data.score} 分`)
    await refreshQuizData()
  } finally {
    submittingQuiz.value = false
  }
}

async function removeQuiz(quiz) {
  await ElMessageBox.confirm(`确定删除「${quiz.title}」及其答题记录？`, '删除确认', {
    type: 'warning',
  })
  await deleteQuiz(quiz.id)
  if (activeQuiz.value?.id === quiz.id) closeQuiz()
  await refreshQuizData()
  ElMessage.success('测验记录已删除')
}

async function jumpToQuizSource(source, questionId) {
  activeTab.value = 'materials'
  await router.replace({
    path: `/courses/${courseId}`,
    query: { material_id: source.material_id, citation: `测验题 ${questionId}` },
  })
  await nextTick()
  document.querySelector('.source-material-row')?.scrollIntoView({
    behavior: 'smooth',
    block: 'center',
  })
}

function scoreText(value) {
  return value === null || value === undefined ? '--' : `${value}`
}

function formatDateTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '--'
}

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

    <el-tabs v-model="activeTab" class="tabs">
      <el-tab-pane label="资料管理" name="materials">
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

      <el-tab-pane label="知识点整理" name="summary">
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

      <el-tab-pane label="阶段测验" name="quiz">
        <template v-if="learningProgress">
          <el-row :gutter="12" class="progress-cards">
            <el-col :xs="12" :sm="6">
              <el-card shadow="never" class="progress-card">
                <div class="progress-value">{{ scoreText(learningProgress.latest_score) }}</div>
                <div class="progress-label">最近成绩</div>
              </el-card>
            </el-col>
            <el-col :xs="12" :sm="6">
              <el-card shadow="never" class="progress-card">
                <div class="progress-value">{{ scoreText(learningProgress.best_score) }}</div>
                <div class="progress-label">历史最好</div>
              </el-card>
            </el-col>
            <el-col :xs="12" :sm="6">
              <el-card shadow="never" class="progress-card">
                <div class="progress-value">{{ learningProgress.combined_progress }}%</div>
                <div class="progress-label">综合学习进度</div>
              </el-card>
            </el-col>
            <el-col :xs="12" :sm="6">
              <el-card shadow="never" class="progress-card">
                <div class="progress-value mastery">{{ learningProgress.mastery_level }}</div>
                <div class="progress-label">掌握状态 · {{ learningProgress.attempts }} 次作答</div>
              </el-card>
            </el-col>
          </el-row>
          <el-alert
            v-if="learningProgress.weak_topics.length"
            class="block"
            type="warning"
            :closable="false"
            show-icon
            :title="`建议优先巩固：${learningProgress.weak_topics.join('、')}`"
            description="薄弱点根据最近 10 次测验中的错题频次动态更新，并参与课程优先级计算。"
          />
        </template>

        <el-card v-if="!activeQuiz" class="block">
          <template #header>
            <div class="filter-row">
              <span>生成阶段性测验</span>
              <el-tag type="success" effect="plain">题目基于本课程资料</el-tag>
            </div>
          </template>
          <el-form label-width="90px" class="quiz-create-form">
            <el-form-item label="学习阶段" required>
              <el-input
                v-model="quizForm.stage"
                maxlength="128"
                placeholder="如：第一阶段、期中复习、第三至五章"
              />
            </el-form-item>
            <el-form-item label="检测重点">
              <el-input
                v-model="quizForm.focus"
                maxlength="256"
                placeholder="如：栈与队列、微分中值定理（不填则综合覆盖）"
              />
            </el-form-item>
            <el-form-item label="题目数量">
              <el-slider v-model="quizForm.question_count" :min="3" :max="10" show-input />
            </el-form-item>
            <el-form-item>
              <el-button
                type="primary"
                :loading="generatingQuiz"
                :disabled="!quizForm.stage.trim()"
                @click="createStageQuiz"
              >
                {{ generatingQuiz ? '正在读取资料并命题…' : '生成测验' }}
              </el-button>
              <span class="quiz-form-tip">自动覆盖不同知识点，提交后给出逐题解析和资料来源</span>
            </el-form-item>
          </el-form>
        </el-card>

        <el-card v-if="activeQuiz" class="block quiz-paper">
          <template #header>
            <div class="filter-row">
              <div>
                <strong>{{ activeQuiz.title }}</strong>
                <el-tag v-if="activeQuiz.agent_mode === 'fallback'" class="ml" type="warning" size="small">
                  离线资料理解题
                </el-tag>
              </div>
              <el-button @click="closeQuiz">返回测验记录</el-button>
            </div>
          </template>
          <el-alert
            v-if="activeQuiz.agent_mode === 'fallback'"
            class="block"
            type="info"
            :closable="false"
            title="当前未配置大模型，系统已根据资料原文生成可核查的理解题；配置 LLM 后可生成概念与应用型题目。"
          />
          <div
            v-for="(question, questionIndex) in activeQuiz.questions"
            :key="question.id"
            class="quiz-question"
            :class="{
              correct: resultByQuestion[question.id]?.correct,
              wrong: quizResult && !resultByQuestion[question.id]?.correct,
            }"
          >
            <div class="question-title">
              <span>{{ questionIndex + 1 }}. {{ question.prompt }}</span>
              <el-tag size="small" effect="plain">{{ question.topic }}</el-tag>
            </div>
            <el-radio-group v-model="quizAnswers[questionIndex]" class="quiz-options" :disabled="!!quizResult">
              <el-radio
                v-for="(option, optionIndex) in question.options"
                :key="optionIndex"
                :label="optionIndex"
                border
              >
                {{ String.fromCharCode(65 + optionIndex) }}. {{ option }}
              </el-radio>
            </el-radio-group>
            <div v-if="resultByQuestion[question.id]" class="question-feedback">
              <div>
                <el-tag :type="resultByQuestion[question.id].correct ? 'success' : 'danger'" size="small">
                  {{ resultByQuestion[question.id].correct ? '回答正确' : '回答错误' }}
                </el-tag>
                <span v-if="!resultByQuestion[question.id].correct" class="correct-answer">
                  正确答案：{{ String.fromCharCode(65 + resultByQuestion[question.id].correct_index) }}
                </span>
              </div>
              <div class="explanation">{{ resultByQuestion[question.id].explanation }}</div>
              <div v-if="resultByQuestion[question.id].source?.material_id" class="quiz-source">
                <span>来源：《{{ resultByQuestion[question.id].source.material_name }}》</span>
                <el-button
                  link
                  type="primary"
                  @click="jumpToQuizSource(resultByQuestion[question.id].source, question.id)"
                >
                  查看原资料
                </el-button>
                <span class="source-excerpt">{{ resultByQuestion[question.id].source.excerpt }}</span>
              </div>
            </div>
          </div>
          <div class="quiz-submit-bar">
            <div v-if="quizResult" class="quiz-score">
              本次得分 <strong>{{ quizResult.score }}</strong> 分，答对
              {{ quizResult.correct_count }}/{{ quizResult.total_count }} 题
            </div>
            <span v-else>已完成 {{ answeredCount }}/{{ activeQuiz.question_count }} 题</span>
            <el-button
              v-if="!quizResult"
              type="primary"
              :loading="submittingQuiz"
              @click="submitActiveQuiz"
            >
              提交并检测学习进度
            </el-button>
            <el-button v-else type="primary" plain @click="openQuiz(activeQuiz)">再测一次</el-button>
          </div>
        </el-card>

        <el-card v-if="!activeQuiz" class="block">
          <template #header>测验记录与成绩趋势</template>
          <el-table :data="quizzes" empty-text="还没有测验，先生成一份阶段测验吧">
            <el-table-column prop="title" label="测验" min-width="160" />
            <el-table-column prop="focus" label="检测重点" min-width="150">
              <template #default="{ row }">{{ row.focus || '综合检测' }}</template>
            </el-table-column>
            <el-table-column prop="question_count" label="题数" width="70" />
            <el-table-column label="最近成绩" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.latest_attempt" :type="row.latest_attempt.score >= 60 ? 'success' : 'danger'">
                  {{ row.latest_attempt.score }} 分
                </el-tag>
                <span v-else>未作答</span>
              </template>
            </el-table-column>
            <el-table-column label="生成时间" min-width="160">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openQuiz(row)">
                  {{ row.latest_attempt ? '重新测验' : '开始作答' }}
                </el-button>
                <el-button link type="danger" @click="removeQuiz(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="learningProgress?.trend.length" class="score-trend">
            <span class="trend-title">最近成绩：</span>
            <div v-for="(attempt, index) in learningProgress.trend" :key="attempt.id" class="trend-item">
              <span>第 {{ index + 1 }} 次</span>
              <strong :class="attempt.score >= 60 ? 'score-pass' : 'score-low'">{{ attempt.score }}</strong>
            </div>
          </div>
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
.progress-cards {
  margin-bottom: 16px;
}
.progress-card {
  margin-bottom: 12px;
  text-align: center;
}
.progress-value {
  min-height: 34px;
  color: #1f4e79;
  font-size: 26px;
  font-weight: 700;
  line-height: 34px;
}
.progress-value.mastery {
  font-size: 18px;
}
.progress-label {
  margin-top: 3px;
  color: #909399;
  font-size: 12px;
}
.quiz-create-form {
  max-width: 720px;
}
.quiz-form-tip {
  margin-left: 12px;
  color: #909399;
  font-size: 12px;
}
.quiz-paper {
  max-width: 1000px;
  margin-right: auto;
  margin-left: auto;
}
.quiz-question {
  padding: 18px;
  margin-bottom: 14px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  transition: border-color 0.2s, background-color 0.2s;
}
.quiz-question.correct {
  border-color: #95d475;
  background: #f0f9eb;
}
.quiz-question.wrong {
  border-color: #fab6b6;
  background: #fef0f0;
}
.question-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  color: #303133;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.7;
}
.quiz-options {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  width: 100%;
}
.quiz-options :deep(.el-radio) {
  box-sizing: border-box;
  width: 100%;
  height: auto;
  min-height: 40px;
  margin: 0;
  padding: 9px 12px;
  white-space: normal;
}
.quiz-options :deep(.el-radio__label) {
  line-height: 1.5;
  white-space: normal;
}
.question-feedback {
  padding-top: 12px;
  margin-top: 14px;
  border-top: 1px dashed #dcdfe6;
}
.correct-answer {
  margin-left: 10px;
  color: #f56c6c;
  font-size: 13px;
  font-weight: 600;
}
.explanation {
  margin-top: 8px;
  color: #606266;
  font-size: 13px;
  line-height: 1.7;
}
.quiz-source {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  color: #606266;
  font-size: 12px;
  flex-wrap: wrap;
}
.source-excerpt {
  width: 100%;
  padding: 7px 9px;
  border-radius: 5px;
  background: rgb(255 255 255 / 70%);
  color: #909399;
  line-height: 1.6;
}
.quiz-submit-bar {
  position: sticky;
  bottom: -20px;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-top: 1px solid #dcdfe6;
  background: rgb(255 255 255 / 96%);
  box-shadow: 0 -4px 12px rgb(0 0 0 / 5%);
}
.quiz-score strong {
  color: #409eff;
  font-size: 24px;
}
.score-trend {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 4px 2px;
  overflow-x: auto;
}
.trend-title {
  color: #606266;
  font-size: 13px;
  white-space: nowrap;
}
.trend-item {
  display: flex;
  min-width: 62px;
  flex-direction: column;
  align-items: center;
  padding: 7px 9px;
  border-radius: 6px;
  background: #f5f7fa;
  color: #909399;
  font-size: 11px;
}
.trend-item strong {
  margin-top: 3px;
  font-size: 16px;
}
.score-pass {
  color: #67c23a;
}
.score-low {
  color: #f56c6c;
}
@media (max-width: 700px) {
  .quiz-options {
    grid-template-columns: 1fr;
  }
  .quiz-form-tip {
    display: block;
    margin: 8px 0 0;
  }
  .quiz-submit-bar {
    bottom: -20px;
  }
}
</style>
