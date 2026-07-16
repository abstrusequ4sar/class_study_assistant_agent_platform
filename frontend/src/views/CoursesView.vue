<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createCourse,
  deleteCourse,
  listCoursePriorities,
  listCourses,
  updateCourse,
} from '../api'

const router = useRouter()
const courses = ref([])
const priorities = ref([])
const dialogVisible = ref(false)
const editingId = ref(null)
const form = reactive({ name: '', description: '', teacher: '', semester: '' })

async function refresh() {
  const [{ data: courseData }, { data: priorityData }] = await Promise.all([
    listCourses(),
    listCoursePriorities(),
  ])
  courses.value = courseData
  priorities.value = priorityData
}
onMounted(refresh)

const priorityMap = computed(() =>
  Object.fromEntries(priorities.value.map((item) => [item.course_id, item])),
)
const sortedCourses = computed(() =>
  [...courses.value].sort(
    (left, right) =>
      (priorityMap.value[left.id]?.rank || 999) - (priorityMap.value[right.id]?.rank || 999),
  ),
)

function priorityOf(courseId) {
  return priorityMap.value[courseId]
}

function priorityTagType(level) {
  return { high: 'danger', medium: 'warning', low: 'success' }[level] || 'info'
}

function progressStatus(value) {
  if (value >= 80) return 'success'
  if (value < 50) return 'exception'
  return ''
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { name: '', description: '', teacher: '', semester: '' })
  dialogVisible.value = true
}

function openEdit(course) {
  editingId.value = course.id
  Object.assign(form, course)
  dialogVisible.value = true
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写课程名称')
    return
  }
  const payload = {
    name: form.name,
    description: form.description,
    teacher: form.teacher,
    semester: form.semester,
  }
  if (editingId.value) {
    await updateCourse(editingId.value, payload)
  } else {
    await createCourse(payload)
  }
  dialogVisible.value = false
  ElMessage.success('保存成功')
  await refresh()
}

async function remove(course) {
  await ElMessageBox.confirm(
    `删除课程《${course.name}》将同时删除其资料与对话记录，确定吗？`,
    '删除确认',
    { type: 'warning' },
  )
  await deleteCourse(course.id)
  ElMessage.success('已删除')
  await refresh()
}
</script>

<template>
  <div>
    <div class="toolbar">
      <h3>我的课程</h3>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建课程
      </el-button>
    </div>

    <el-alert
      v-if="courses.length"
      class="priority-tip"
      type="info"
      :closable="false"
      show-icon
      title="课程已按动态优先级排序"
      description="系统综合任务截止时间、未完成任务量、学习计划期限、任务完成率和最近阶段测验成绩实时计算；完成任务或提交测验后会自动更新。"
    />

    <el-empty v-if="!courses.length" description="还没有课程，点击右上角创建第一门课程吧" />

    <el-row :gutter="16">
      <el-col v-for="course in sortedCourses" :key="course.id" :xs="24" :sm="12" :md="8" :lg="6">
        <el-card class="course-card" shadow="hover" @click="router.push(`/courses/${course.id}`)">
          <div class="course-heading">
            <div class="course-name">{{ course.name }}</div>
            <el-tooltip v-if="priorityOf(course.id)" placement="top" :show-after="300">
              <template #content>
                <div class="priority-tooltip">
                  <div v-for="reason in priorityOf(course.id).reasons" :key="reason">· {{ reason }}</div>
                </div>
              </template>
              <el-tag :type="priorityTagType(priorityOf(course.id).level)" size="small">
                #{{ priorityOf(course.id).rank }} {{ priorityOf(course.id).level_label }}
              </el-tag>
            </el-tooltip>
          </div>
          <div class="course-meta">
            <el-tag v-if="course.semester" size="small">{{ course.semester }}</el-tag>
            <span v-if="course.teacher" class="teacher">{{ course.teacher }}</span>
          </div>
          <div class="course-desc">{{ course.description || '暂无简介' }}</div>
          <div v-if="priorityOf(course.id)" class="priority-panel">
            <div class="priority-score-row">
              <span>优先级 {{ priorityOf(course.id).score }} 分</span>
              <span>学习进度 {{ priorityOf(course.id).progress }}%</span>
            </div>
            <el-progress
              :percentage="priorityOf(course.id).progress"
              :status="progressStatus(priorityOf(course.id).progress)"
              :stroke-width="6"
              :show-text="false"
            />
            <div class="priority-reason">{{ priorityOf(course.id).reasons[0] }}</div>
          </div>
          <div class="course-actions" @click.stop>
            <el-button size="small" @click="router.push(`/courses/${course.id}/chat`)">
              <el-icon><ChatDotRound /></el-icon>问答
            </el-button>
            <el-button size="small" @click="openEdit(course)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="remove(course)">删除</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑课程' : '新建课程'"
      width="480px"
    >
      <el-form label-width="80px">
        <el-form-item label="课程名称" required>
          <el-input v-model="form.name" maxlength="128" />
        </el-form-item>
        <el-form-item label="授课教师">
          <el-input v-model="form.teacher" maxlength="64" />
        </el-form-item>
        <el-form-item label="学期">
          <el-input v-model="form.semester" placeholder="如 2026春" maxlength="32" />
        </el-form-item>
        <el-form-item label="课程简介">
          <el-input v-model="form.description" type="textarea" :rows="3" maxlength="2000" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.course-card {
  margin-bottom: 16px;
  cursor: pointer;
}
.priority-tip {
  margin-bottom: 16px;
}
.course-heading {
  display: flex;
  min-height: 24px;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.course-name {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 8px;
}
.priority-panel {
  padding: 9px 10px;
  margin-bottom: 12px;
  border-radius: 7px;
  background: #f7f9fc;
}
.priority-score-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
  color: #606266;
  font-size: 12px;
}
.priority-reason {
  margin-top: 5px;
  overflow: hidden;
  color: #909399;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.priority-tooltip {
  max-width: 260px;
  line-height: 1.7;
}
.course-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
.teacher {
  font-size: 13px;
  color: #909399;
}
.course-desc {
  font-size: 13px;
  color: #606266;
  min-height: 36px;
  margin-bottom: 12px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
