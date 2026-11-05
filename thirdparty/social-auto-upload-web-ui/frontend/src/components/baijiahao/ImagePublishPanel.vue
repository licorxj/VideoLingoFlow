<template>
  <div class="baijiahao-image-publish-panel">
    <div v-if="accountId && hasAccountOverride(accountId)" style="margin-bottom: 12px;">
      <el-button size="small" @click="resetOverride">恢复为渠道默认</el-button>
    </div>

    <div class="setting-card" style="grid-column: 1 / -1">
      <div class="setting-label">标题</div>
      <div class="setting-hint">文章标题,2~64 字(emoji 按 3 字算)</div>
      <el-input v-model="form.title" placeholder="请输入标题..." maxlength="64" show-word-limit :disabled="disabled" />
    </div>

    <div class="setting-card" style="grid-column: 1 / -1">
      <div class="setting-label">正文</div>
      <div class="setting-hint">作为文章正文发布,图片将作为插图插入正文,换行自动分段</div>
      <el-input v-model="form.description" type="textarea" :rows="6" placeholder="请输入正文..." maxlength="20000" show-word-limit :disabled="disabled" />
    </div>

    <div class="setting-card" style="grid-column: 1 / -1">
      <div class="setting-label">标签</div>
      <div class="setting-hint">输入标签内容,按回车确认(最多 10 个,以 #话题 行追加到文末)</div>
      <el-input v-model="tagInput" placeholder="输入标签内容，按回车添加" @keyup.enter="addTag" clearable :disabled="disabled" />
      <div v-if="form.tags && form.tags.length > 0" class="tags-list">
        <el-tag v-for="(tag, index) in form.tags" :key="index" closable @close="removeTag(index)" size="small" :disable-transitions="false">#{{ tag }}</el-tag>
      </div>
    </div>

    <div class="setting-card">
      <div class="setting-label">必选声明</div>
      <el-select v-model="form.creationDeclaration" placeholder="选择必选声明" style="width: 100%" :disabled="disabled">
        <el-option v-for="opt in creationOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
    </div>

    <div class="setting-card">
      <div class="setting-label">补充声明</div>
      <el-select v-model="form.supplementaryDeclaration" placeholder="选择补充声明（可选）" clearable style="width: 100%" :disabled="disabled">
        <el-option v-for="opt in supplementaryOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useAccountStore } from '@/stores/account'
import { imagePublishApi } from '@/api/imagePublish'
import { PLATFORMS } from '@/config/platforms'
import { useChannelForm } from '@/composables/useChannelForm'

const props = defineProps({
  accountId: { type: [Number, Object], default: null },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['config-changed', 'publish-result'])

const accountStore = useAccountStore()

const BAIJIAHAO_DEFAULTS = { ...PLATFORMS.BAIJIAHAO.defaultSettings, tags: [] }
const MAX_TAGS = 10

const creationOptions = computed(() => {
  const field = PLATFORMS.BAIJIAHAO.settingsFields.find(f => f.key === 'creationDeclaration')
  return field?.options || []
})

const supplementaryOptions = computed(() => {
  const field = PLATFORMS.BAIJIAHAO.settingsFields.find(f => f.key === 'supplementaryDeclaration')
  return field?.options || []
})

const { form, hasAccountOverride, resetOverride, publicApi } = useChannelForm(
  BAIJIAHAO_DEFAULTS,
  { props, emit },
  {
    publishFn: async (accountId, accountName, commonData, merged, extra) => {
      const account = accountStore.accounts.find(a => a.id === accountId)
      if (!account) {
        emit('publish-result', { accountName, status: 'fail', message: '账号不存在' })
        return
      }
      try {
        await imagePublishApi.publishImage({
          image_ids: commonData.images.map(img => img.id),
          account_configs: {
            account_id: accountId, platform: account.platform, filePath: account.filePath,
            title: merged.title || '', description: merged.description || '',
            tags: (merged.tags || []).slice(0, MAX_TAGS), scheduleTime: merged.scheduleTime || '',
            creationDeclaration: merged.creationDeclaration || '',
            supplementaryDeclaration: merged.supplementaryDeclaration || '',
            cover_path: commonData.coverImage?.stored_path || '',
            dry_run: false,
          },
          batchId: extra?.batchId || '',
        })
        emit('publish-result', { accountName, status: 'success', message: '发布成功' })
      } catch (e) {
        emit('publish-result', { accountName, status: 'fail', message: e.message || '发布失败' })
      }
    },
    validateFn: (accountId, merged) => {
      const errors = []
      const t = merged.title || ''
      if (!t.trim()) errors.push('标题不能为空')
      else if (t.length < 2 || t.length > 64) errors.push('标题需 2~64 字(emoji 按 3 字算)')
      if (!merged.description || !merged.description.trim()) errors.push('正文不能为空')
      if (!merged.creationDeclaration) errors.push('请选择必选声明')
      if ((merged.tags?.length || 0) > MAX_TAGS) errors.push(`标签最多 ${MAX_TAGS} 个`)
      return { valid: errors.length === 0, errors }
    },
  },
)

// ===== Tag input =====
const tagInput = ref('')

function addTag() {
  const tag = tagInput.value.trim()
  if (!tag) return
  if ((form.tags?.length || 0) >= MAX_TAGS) {
    ElMessage.warning(`标签最多 ${MAX_TAGS} 个`)
    return
  }
  if (!form.tags) form.tags = []
  if (form.tags.includes(tag)) { ElMessage.warning('标签已存在'); return }
  form.tags.push(tag)
  tagInput.value = ''
}

function removeTag(index) { form.tags.splice(index, 1) }

defineExpose(publicApi)
</script>

<style scoped>
.baijiahao-image-publish-panel {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 12px;
}

.setting-card {
  border: 1px solid rgba(230, 78, 58, 0.15);
  background: rgba(230, 78, 58, 0.04);
  border-radius: 8px;
  padding: 16px;
}

.setting-label {
  font-size: 13px;
  font-weight: 600;
  color: #e64e3a;
  margin-bottom: 8px;
}

.setting-hint {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
  line-height: 1.5;
}

.tags-list {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>
