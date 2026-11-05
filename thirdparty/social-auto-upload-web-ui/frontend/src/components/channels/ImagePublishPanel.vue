<template>
  <div class="channels-image-publish-panel">
    <div v-if="accountId && hasAccountOverride(accountId)" style="margin-bottom: 12px;">
      <el-button size="small" @click="resetOverride">恢复为渠道默认</el-button>
    </div>

    <div class="setting-card" style="grid-column: 1 / -1">
      <div class="setting-label">标题</div>
      <div class="setting-hint">图片动态标题,最多 22 个字符</div>
      <el-input v-model="form.title" placeholder="请输入标题..." maxlength="22" show-word-limit :disabled="disabled" />
    </div>

    <div class="setting-card" style="grid-column: 1 / -1">
      <div class="setting-label">描述</div>
      <div class="setting-hint">图片动态正文,最多 9 张图片(超出将被拒绝)</div>
      <el-input v-model="form.description" type="textarea" :rows="5" placeholder="请输入描述..." maxlength="1000" show-word-limit :disabled="disabled" />
    </div>

    <div class="setting-card" style="grid-column: 1 / -1">
      <div class="setting-label">标签</div>
      <div class="setting-hint">输入标签内容,按回车确认(最多 10 个,以 #话题 形式追加到描述)</div>
      <el-input v-model="tagInput" placeholder="输入标签内容，按回车添加" @keyup.enter="addTag" clearable :disabled="disabled" />
      <div v-if="form.tags && form.tags.length > 0" class="tags-list">
        <el-tag v-for="(tag, index) in form.tags" :key="index" closable @close="removeTag(index)" size="small" :disable-transitions="false">#{{ tag }}</el-tag>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { PLATFORMS } from '@/config/platforms'
import { imagePublishApi } from '@/api/imagePublish'
import { useChannelForm } from '@/composables/useChannelForm'

const props = defineProps({
  accountId: { type: [Number, Object], default: null },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['config-changed', 'publish-result'])

const CHANNELS_DEFAULTS = { ...PLATFORMS.CHANNELS.defaultSettings, tags: [] }
const MAX_TAGS = 10

const { form, hasAccountOverride, resetOverride, publicApi } = useChannelForm(
  CHANNELS_DEFAULTS,
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
            title: (merged.title || '').slice(0, 22), description: merged.description || '',
            tags: (merged.tags || []).slice(0, MAX_TAGS), scheduleTime: merged.scheduleTime || '',
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
      if (!merged.title || !merged.title.trim()) errors.push('标题不能为空')
      if ((merged.title || '').length > 22) errors.push('标题最多 22 个字符')
      if ((merged.tags?.length || 0) > MAX_TAGS) errors.push(`标签最多 ${MAX_TAGS} 个`)
      return { valid: errors.length === 0, errors }
    },
  },
)

import { useAccountStore } from '@/stores/account'
const accountStore = useAccountStore()

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
.channels-image-publish-panel {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 12px;
}

.setting-card {
  border: 1px solid rgba(59, 130, 246, 0.15);
  background: rgba(59, 130, 246, 0.04);
  border-radius: 8px;
  padding: 16px;
}

.setting-label {
  font-size: 13px;
  font-weight: 600;
  color: #3b82f6;
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
