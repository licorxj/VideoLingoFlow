<template>
  <el-dialog
    v-model="visible"
    :title="dialogTitle"
    width="640px"
    align-center
    :close-on-click-modal="false"
    class="account-default-config-dialog"
    @closed="onClosed"
  >
    <div v-if="account" class="adc-body">
      <div class="adc-tip">
        <el-icon><InfoFilled /></el-icon>
        <span>
          为账号「{{ account.name }}」设置默认发布配置。发布时自动套用为初始值，
          MCP / 程序化发布不传这些参数时也会自动使用；本次发布仍可在发布中心按账号单独覆盖。
        </span>
      </div>

      <el-form label-position="top" class="adc-form">
        <!-- 账号级合集 / 位置(不在 settingsFields 里的专属字段) -->
        <template v-if="extraFields.length">
          <div class="adc-section-title">合集 / 位置</div>
          <div class="adc-grid">
            <el-form-item
              v-for="f in extraFields"
              :key="f.key"
              :label="f.label"
              :class="{ 'full-row': f.fullRow }"
            >
              <el-input
                v-model="form[f.key]"
                :placeholder="f.placeholder || '留空则不设置'"
                clearable
              />
              <div v-if="f.description" class="adc-field-desc">{{ f.description }}</div>
            </el-form-item>
          </div>
        </template>

        <!-- 平台 settingsFields(排除每次发布变化的内容字段) -->
        <template v-if="settingFields.length">
          <div class="adc-section-title">平台发布设置</div>
          <div class="adc-grid">
            <template v-for="f in settingFields" :key="f.key">
              <el-form-item
                v-if="isFieldVisible(f)"
                :label="f.label"
                :class="{ 'full-row': f.fullRow }"
              >
                <!-- 开关 -->
                <template v-if="f.type === 'switch'">
                  <div class="adc-switch-row">
                    <el-switch v-model="form[f.key]" :disabled="isFieldDisabled(f)" />
                    <span v-if="f.description" class="adc-field-desc">{{ f.description }}</span>
                  </div>
                </template>
                <!-- 单选 -->
                <template v-else-if="f.type === 'radio'">
                  <el-radio-group v-model="form[f.key]" :disabled="isFieldDisabled(f)">
                    <el-radio v-for="opt in (f.options || [])" :key="String(opt.value)" :value="opt.value">
                      {{ opt.label }}
                    </el-radio>
                  </el-radio-group>
                </template>
                <!-- 下拉 -->
                <template v-else-if="f.type === 'select'">
                  <el-select
                    v-model="form[f.key]"
                    :placeholder="f.placeholder || '请选择'"
                    clearable
                    filterable
                    style="width: 100%"
                    :disabled="isFieldDisabled(f)"
                  >
                    <el-option
                      v-for="opt in (f.options || [])"
                      :key="String(opt.value)"
                      :label="opt.label"
                      :value="opt.value"
                    />
                  </el-select>
                </template>
                <!-- 级联(拍摄地区等) -->
                <template v-else-if="f.type === 'cascader'">
                  <el-cascader
                    v-model="form[f.key]"
                    :options="f.options || []"
                    :props="{ ...(f.props || {}), checkStrictly: true }"
                    :placeholder="f.placeholder || '请选择'"
                    clearable
                    filterable
                    style="width: 100%"
                    :disabled="isFieldDisabled(f)"
                  />
                </template>
                <!-- 日期 -->
                <template v-else-if="f.type === 'date'">
                  <el-date-picker
                    v-model="form[f.key]"
                    type="date"
                    value-format="YYYY-MM-DD"
                    :placeholder="f.placeholder || '选择日期'"
                    style="width: 100%"
                    :disabled="isFieldDisabled(f)"
                  />
                </template>
                <!-- poiSelect / compilationSelect 降级为纯文本输入(后端消费名称字符串) -->
                <template v-else-if="f.type === 'poiSelect' || f.type === 'compilationSelect'">
                  <el-input
                    v-model="form[f.key]"
                    :placeholder="f.placeholder || '输入名称(留空则不设置)'"
                    clearable
                    :disabled="isFieldDisabled(f)"
                  />
                </template>
                <!-- 其它(文本) -->
                <template v-else>
                  <el-input
                    v-model="form[f.key]"
                    :placeholder="f.placeholder || '请输入'"
                    clearable
                    :disabled="isFieldDisabled(f)"
                  />
                </template>
                <div v-if="f.description && f.type !== 'switch'" class="adc-field-desc">{{ f.description }}</div>
              </el-form-item>
            </template>
          </div>
        </template>

        <el-empty v-if="!extraFields.length && !settingFields.length" description="该平台暂无可配置的默认项" />
      </el-form>
    </div>

    <template #footer>
      <div class="adc-footer">
        <el-button text @click="clearAll">清空全部</el-button>
        <div class="adc-footer-right">
          <el-button @click="visible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="save">保存默认配置</el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { accountApi } from '@/api/account'
import { getPlatformByName } from '@/config/platforms'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  account: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const visible = ref(false)
watch(() => props.modelValue, (v) => {
  visible.value = v
  if (v) initForm()
})
watch(visible, (v) => emit('update:modelValue', v))

const saving = ref(false)
const form = reactive({})

const platformConf = computed(() => props.account ? getPlatformByName(props.account.platform) : null)
const dialogTitle = computed(() => {
  const name = platformConf.value?.name || props.account?.platform || ''
  return `默认发布配置${name ? ' · ' + name : ''}`
})

// 每次发布都会变化的内容字段,不作为账号默认
const CONTENT_KEYS = new Set([
  'title', 'description', 'tags', 'videoFormat', 'scheduleTime', 'enableTimer',
  'aiContent', 'coverPath', 'videoPath',
])
// settingsFields 里支持渲染的类型(内容字段已排除)
const SUPPORTED_TYPES = new Set([
  'switch', 'radio', 'select', 'input', 'date', 'datetime', 'cascader',
  'poiSelect', 'compilationSelect',
])

const settingFields = computed(() => {
  const fields = platformConf.value?.settingsFields || []
  return fields.filter(f => !CONTENT_KEYS.has(f.key) && SUPPORTED_TYPES.has(f.type))
})

// 账号级合集 / 位置字段(不在 settingsFields 里,发布页为账号级 RemoteSearchSelect 卡片)
// 后端 merge_config 白名单 + build_platform_kwargs 消费的是名称字符串 / id,纯文本可配置。
const EXTRA_FIELDS_BY_KEY = {
  douyin: [
    { key: 'mixId', label: '默认合集 ID', placeholder: '抖音合集 mix_id(留空则不加入合集)', fullRow: true },
  ],
  xiaohongshu: [
    { key: 'collectionName', label: '默认合集名称', placeholder: '输入合集名称(留空则不加入合集)' },
    { key: 'collectionId', label: '默认合集 ID', placeholder: '可选,填了更精确' },
  ],
  bilibili: [
    { key: 'biliCollectionName', label: '默认合集名称', placeholder: '输入 B 站合集名称(留空则不加入合集)', fullRow: true },
  ],
  channels: [
    { key: 'channelsCollectionName', label: '默认合集名称', placeholder: '输入视频号合集名称(留空则不加入合集)' },
    { key: 'channelsLocationName', label: '默认位置', placeholder: '输入地理位置名称(留空则不显示位置)' },
  ],
  weibo: [
    { key: 'weiboCollectionName', label: '默认合集名称', placeholder: '输入微博合集名称(留空则不加入合集)', fullRow: true },
  ],
  weixin_gzh: [
    { key: 'gzhCollectionName', label: '默认合集名称', placeholder: '输入公众号合集名称(留空则不加入合集)', fullRow: true },
  ],
}
const extraFields = computed(() => {
  const key = platformConf.value?.key
  return key ? (EXTRA_FIELDS_BY_KEY[key] || []) : []
})

function isFieldVisible(f) {
  const vw = f.visibleWhen
  if (!vw) return true
  // 支持 value 为单值或数组
  if (Array.isArray(vw.value)) return vw.value.includes(form[vw.key])
  return form[vw.key] === vw.value
}
function isFieldDisabled(f) {
  const dw = f.disabledWhen
  if (!dw) return false
  if (Array.isArray(dw.value)) return dw.value.includes(form[dw.key])
  return form[dw.key] === dw.value
}

function initForm() {
  Object.keys(form).forEach(k => delete form[k])
  const defaults = platformConf.value?.defaultSettings || {}
  const saved = (props.account && typeof props.account.defaultConfig === 'object' && props.account.defaultConfig)
    ? props.account.defaultConfig : {}
  // 以平台默认值为底,叠加账号已保存配置
  const allKeys = new Set([...settingFields.value.map(f => f.key), ...extraFields.value.map(f => f.key)])
  allKeys.forEach(k => {
    // cascader 需要数组默认值
    if (Array.isArray(defaults[k])) form[k] = saved[k] !== undefined ? saved[k] : [...defaults[k]]
    else form[k] = saved[k] !== undefined ? saved[k] : (defaults[k] !== undefined ? defaults[k] : '')
  })
}

function clearAll() {
  Object.keys(form).forEach(k => {
    const def = (platformConf.value?.defaultSettings || {})[k]
    form[k] = Array.isArray(def) ? [] : ''
  })
}

async function save() {
  if (!props.account) return
  // 只保存非空(有实际意义)的字段,布尔 False 也保留(它是显式值,可覆盖平台默认 True)
  const payload = {}
  Object.keys(form).forEach(k => {
    const v = form[k]
    if (v === '' || v === null || v === undefined) return
    if (Array.isArray(v) && v.length === 0) return
    payload[k] = v
  })
  saving.value = true
  try {
    await accountApi.updateAccount({ id: props.account.id, defaultConfig: payload })
    ElMessage.success('默认发布配置已保存')
    emit('saved', { id: props.account.id, defaultConfig: payload })
    visible.value = false
  } catch (e) {
    ElMessage.error('保存失败:' + (e?.message || e))
  } finally {
    saving.value = false
  }
}

function onClosed() {
  saving.value = false
}
</script>

<style scoped>
.adc-body {
  max-height: 62vh;
  overflow-y: auto;
  padding-right: 6px;
}
.adc-tip {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 10px 12px;
  margin-bottom: 16px;
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.2);
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.6;
  color: #475569;
}
.adc-tip .el-icon { color: #3b82f6; margin-top: 2px; flex-shrink: 0; }
.adc-section-title {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
  margin: 6px 0 12px;
  padding-left: 8px;
  border-left: 3px solid #6366f1;
}
.adc-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 20px;
}
.adc-grid :deep(.el-form-item) { margin-bottom: 14px; }
.adc-grid :deep(.full-row) { grid-column: 1 / -1; }
.adc-grid :deep(.el-form-item__label) { font-size: 12px; color: #475569; padding-bottom: 4px; }
.adc-switch-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.adc-field-desc { font-size: 11px; color: #94a3b8; line-height: 1.5; margin-top: 2px; }
.adc-footer { display: flex; justify-content: space-between; align-items: center; }
.adc-footer-right { display: flex; gap: 8px; }
</style>
