<template>
  <div class="toutiao-image-publish-panel">
    <div v-if="accountId && hasAccountOverride(accountId)" style="margin-bottom: 12px;">
      <el-button size="small" @click="resetOverride">恢复为渠道默认</el-button>
    </div>

    <div class="setting-card" style="grid-column: 1 / -1">
      <div class="setting-label">标题</div>
      <div class="setting-hint">文章标题,2~30 个字</div>
      <el-input v-model="form.title" placeholder="请输入文章标题..." maxlength="30" show-word-limit :disabled="disabled" />
    </div>

    <div class="setting-card" style="grid-column: 1 / -1">
      <div class="setting-label">正文</div>
      <div class="setting-hint">作为文章正文发布,图片将作为插图插入正文,换行自动分段;文章编辑器无标签/声明控件</div>
      <el-input v-model="form.description" type="textarea" :rows="6" placeholder="请输入正文..." maxlength="20000" show-word-limit :disabled="disabled" />
    </div>
  </div>
</template>

<script setup>
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

const TOUTIAO_DEFAULTS = { ...PLATFORMS.TOUTIAO.defaultSettings, tags: [] }

const { form, hasAccountOverride, resetOverride, publicApi } = useChannelForm(
  TOUTIAO_DEFAULTS,
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
            scheduleTime: merged.scheduleTime || '',
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
      else if (t.length < 2 || t.length > 30) errors.push('标题需 2~30 个字')
      if (!merged.description || !merged.description.trim()) errors.push('正文不能为空')
      return { valid: errors.length === 0, errors }
    },
  },
)

defineExpose(publicApi)
</script>

<style scoped>
.toutiao-image-publish-panel {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 12px;
}

.setting-card {
  border: 1px solid rgba(255, 0, 0, 0.15);
  background: rgba(255, 0, 0, 0.04);
  border-radius: 8px;
  padding: 16px;
}

.setting-label {
  font-size: 13px;
  font-weight: 600;
  color: #FF0000;
  margin-bottom: 8px;
}

.setting-hint {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
  line-height: 1.5;
}
</style>
