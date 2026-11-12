<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="page-title">用户管理</h2>
        <p class="page-sub">每个站内账号绑定一个飞牛用户，并各自授权自己的 Trakt 账号。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新建用户</el-button>
      </div>
    </div>

    <div class="role-banner">
      <div class="role-item">
        <span class="chip info">管理员</span>
        <span>分配 / 绑定飞牛用户，管理系统设置与 Trakt 应用凭据，查看全部数据。</span>
      </div>
      <div class="role-item">
        <span class="chip success">普通用户</span>
        <span>只能查看自己的观看记录，并使用设备授权码绑定自己的 Trakt 账号；看不到应用凭据。</span>
      </div>
    </div>

    <div class="panel">
      <el-table v-loading="loading" :data="users" style="width: 100%">
        <el-table-column label="用户" min-width="180">
          <template #default="{ row }">
            <div class="user-cell">
              <div class="avatar">{{ row.username.slice(0, 1).toUpperCase() }}</div>
              <div>
                <div style="font-weight: 650">{{ row.username }}</div>
                <div class="tiny muted">创建于 {{ formatDate(row.created_at) }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <span class="chip" :class="row.role === 'admin' ? 'info' : 'muted'">
              {{ row.role === 'admin' ? '管理员' : '普通用户' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="飞牛用户" width="140">
          <template #default="{ row }">
            <span v-if="row.fn_username" class="chip muted">{{ row.fn_username }}</span>
            <span v-else class="muted tiny">未绑定</span>
          </template>
        </el-table-column>
        <el-table-column label="Trakt" width="150">
          <template #default="{ row }">
            <span v-if="row.trakt" class="chip success">@{{ row.trakt.trakt_username }}</span>
            <span v-else class="chip warning">未绑定</span>
          </template>
        </el-table-column>
        <el-table-column label="已看完" width="90">
          <template #default="{ row }">{{ row.completed_count }} 条</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <span class="chip" :class="row.is_active ? 'success' : 'danger'">{{ row.is_active ? '启用' : '禁用' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="最后登录" width="160">
          <template #default="{ row }">{{ formatDateTime(row.last_login_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" text type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog append-to-body v-model="createVisible" title="新建用户" width="480px">
      <el-form label-position="top">
        <el-form-item label="用户名">
          <el-input v-model="createForm.username" placeholder="登录用户名" />
        </el-form-item>
        <el-form-item label="初始密码">
          <el-input v-model="createForm.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="createForm.role">
            <el-radio value="user">普通用户</el-radio>
            <el-radio value="admin">管理员</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="绑定飞牛用户（可稍后分配）">
          <el-select v-model="createForm.fn_user_guid" clearable placeholder="选择飞牛用户" style="width: 100%">
            <el-option
              v-for="u in fnUsers"
              :key="u.guid"
              :label="u.bound ? u.username + '（已绑定）' : u.username"
              :value="u.guid"
              :disabled="u.bound"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="create">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog append-to-body v-model="editVisible" :title="`编辑 ${editForm.username}`" width="480px">
      <el-form label-position="top">
        <el-form-item label="角色">
          <el-radio-group v-model="editForm.role">
            <el-radio value="user">普通用户</el-radio>
            <el-radio value="admin">管理员</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="账号状态">
          <el-switch v-model="editForm.is_active" active-text="启用" inactive-text="禁用" />
        </el-form-item>
        <el-form-item label="绑定飞牛用户">
          <el-select v-model="editForm.fn_user_guid" clearable placeholder="选择飞牛用户" style="width: 100%">
            <el-option
              v-for="u in fnUsers"
              :key="u.guid"
              :label="u.bound && u.guid !== editForm.fn_user_guid ? u.username + '（已绑定）' : u.username"
              :value="u.guid"
              :disabled="u.bound && u.guid !== editForm.fn_user_guid"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="重置密码（留空不修改）">
          <el-input v-model="editForm.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import api, { errMsg } from '@/api/client'
import { formatDate, formatDateTime } from '@/utils/format'

const loading = ref(false)
const saving = ref(false)
const users = ref([])
const fnUsers = ref([])
const createVisible = ref(false)
const editVisible = ref(false)
const createForm = reactive({ username: '', password: '', role: 'user', fn_user_guid: '' })
const editForm = reactive({ id: null, username: '', role: 'user', is_active: true, fn_user_guid: '', password: '' })

async function load() {
  loading.value = true
  try {
    const [userData, fnData] = await Promise.all([api.get('/users'), api.get('/fntv/users')])
    users.value = userData.items
    fnUsers.value = fnData.items
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  createForm.username = ''
  createForm.password = ''
  createForm.role = 'user'
  createForm.fn_user_guid = ''
  createVisible.value = true
}

async function create() {
  if (createForm.username.trim().length < 2 || createForm.password.length < 6) {
    ElMessage.warning('用户名至少 2 位，密码至少 6 位')
    return
  }
  saving.value = true
  try {
    await api.post('/users', {
      username: createForm.username.trim(),
      password: createForm.password,
      role: createForm.role,
      fn_user_guid: createForm.fn_user_guid || null
    })
    ElMessage.success('用户已创建')
    createVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    saving.value = false
  }
}

function openEdit(row) {
  editForm.id = row.id
  editForm.username = row.username
  editForm.role = row.role
  editForm.is_active = row.is_active
  editForm.fn_user_guid = row.fn_user_guid || ''
  editForm.password = ''
  editVisible.value = true
}

async function saveEdit() {
  saving.value = true
  try {
    await api.patch(`/users/${editForm.id}`, {
      role: editForm.role,
      is_active: editForm.is_active,
      fn_user_guid: editForm.fn_user_guid || null,
      password: editForm.password || null
    })
    ElMessage.success('已保存')
    editVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确定删除用户「${row.username}」吗？该操作不可撤销。`, '删除用户', { type: 'warning' })
    await api.delete(`/users/${row.id}`)
    ElMessage.success('已删除')
    await load()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(errMsg(error))
  }
}

onMounted(load)
</script>

<style scoped>
.role-banner {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  padding: 15px 18px;
  margin-bottom: 16px;
  border-radius: 18px;
  background: var(--glass);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow-sm), var(--shadow-inset);
  backdrop-filter: blur(16px);
}
.role-item { display: flex; align-items: center; gap: 10px; font-size: 12.5px; color: var(--muted); }
.user-cell { display: flex; align-items: center; gap: 10px; }
.avatar {
  width: 34px;
  height: 34px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  color: var(--on-primary);
  font-weight: 700;
  background: var(--primary-grad);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.55);
}
</style>
