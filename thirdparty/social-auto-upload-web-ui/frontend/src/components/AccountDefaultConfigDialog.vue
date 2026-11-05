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
              <!-- 合集类:保留手填,同时支持「获取合集数据」→ 下拉快捷选择 -->
              <template v-if="f.fetchKind === 'collection'">
                <div class="adc-fetch-row">
                  <el-autocomplete
                    v-model="form[f.key]"
                    :fetch-suggestions="(qs, cb) => queryCollection(f, qs, cb)"
                    :placeholder="f.placeholder || '留空则不设置'"
                    clearable
                    class="adc-fetch-input"
                    @select="(item) => onCollectionSelect(f, item)"
                  >
                    <template #default="{ item }">
                      <span class="adc-opt-name">{{ item.value }}</span>
                      <span v-if="item.desc" class="adc-opt-desc">{{ item.desc }}</span>
                    </template>
                  </el-autocomplete>
                  <el-button
                    size="small"
                    class="adc-fetch-btn"
                    :loading="!!loadingMap[f.key]"
                    @click="loadCollectionData(f)"
                  >获取合集数据</el-button>
                </div>
                <div class="adc-field-desc">
                  {{ collectionOptions[f.key]?.length
                    ? `已获取 ${collectionOptions[f.key].length} 个合集,聚焦输入框即可下拉选择`
                    : '点击右侧按钮拉取该账号的合集列表;也可直接手填名称' }}
                </div>
              </template>
              <el-input
                v-else
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
import { biliApi } from '@/api/bilibili'
import { xhsApi } from '@/api/xiaohongshu'
import { channelsApi } from '@/api/channels'
import { weiboApi } from '@/api/weibo'
import { weixinGzhApi } from '@/api/weixin_gzh'
import { douyinImageApi } from '@/api/douyinImage'
import { toutiaoApi } from '@/api/toutiao'

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
    // 字段名是 mixId,但后端 _set_image_mix 是按文本匹配(has-text),发布页存的也是 mix_name,
    // 因此这里的值语义 = 合集名称,与其余平台保持一致
    { key: 'mixId', label: '默认合集', placeholder: '输入抖音合集名称(留空则不加入合集)', fullRow: true, fetchKind: 'collection' },
  ],
  xiaohongshu: [
    { key: 'collectionName', label: '默认合集名称', placeholder: '输入合集名称(留空则不加入合集)', fetchKind: 'collection', idKey: 'collectionId' },
    { key: 'collectionId', label: '默认合集 ID', placeholder: '可选,选了合集会自动填入' },
  ],
  bilibili: [
    { key: 'biliCollectionName', label: '默认合集名称', placeholder: '输入 B 站合集名称(留空则不加入合集)', fullRow: true, fetchKind: 'collection' },
  ],
  channels: [
    { key: 'channelsCollectionName', label: '默认合集名称', placeholder: '输入视频号合集名称(留空则不加入合集)', fetchKind: 'collection' },
    { key: 'channelsLocationName', label: '默认位置', placeholder: '输入地理位置名称(留空则不显示位置)' },
  ],
  weibo: [
    { key: 'weiboCollectionName', label: '默认合集名称', placeholder: '输入微博合集名称(留空则不加入合集)', fullRow: true, fetchKind: 'collection' },
  ],
  weixin_gzh: [
    { key: 'gzhCollectionName', label: '默认合集名称', placeholder: '输入公众号合集名称(留空则不加入合集)', fullRow: true, fetchKind: 'collection' },
  ],
  // 今日头条:后端 _set_collection 按 collection_id(合集 ID)匹配;
  // 后端 /compilation-search 拉取合集列表,下拉回填 ID(而非名称)
  toutiao: [
    { key: 'collection_id', label: '默认合集', placeholder: '输入今日头条合集名称或 ID(留空则不加入合集)', fullRow: true, fetchKind: 'collection', valueKey: 'id' },
  ],
  // 快手 / 百家号:后端暂未接入「获取合集数据」(需真实账号校准合集 DOM),
  // 先提供手动填写,后端 _set_collection 设置逻辑已就位(selector 待校准)
  kuaishou: [
    { key: 'kuaishouCollectionName', label: '默认合集名称', placeholder: '输入快手合集名称(留空则不加入合集)', fullRow: true, description: '暂需手动填写;「获取合集数据」按钮待平台 DOM 校准后接入' },
  ],
  baijiahao: [
    { key: 'baijiahaoCollectionName', label: '默认合集名称', placeholder: '输入百家号合集名称(留空则不加入合集)', fullRow: true, description: '暂需手动填写;「获取合集数据」按钮待平台 DOM 校准后接入' },
  ],
}
const extraFields = computed(() => {
  const key = platformConf.value?.key
  const list = key ? (EXTRA_FIELDS_BY_KEY[key] || []) : []
  // 带「获取合集数据」按钮的字段占整行,避免两列布局下输入框被按钮挤窄
  return list.map(f => (f.fetchKind ? { ...f, fullRow: true } : f))
})

// ============ 合集数据:「获取合集数据」按钮 → 下拉快捷选择(同时保留手填) ============
// 各平台接口契约不同,统一归一为 [{ id, name, desc }]
const COLLECTION_FETCHERS = {
  bilibili: (accountId) => biliApi.getCollections(accountId).then(r => r.data?.list || []),
  xiaohongshu: (accountId) => xhsApi.getCollections(accountId).then(r => r.data?.list || []),
  channels: (accountId) => channelsApi.getCollections(accountId).then(r => r.data?.list || []),
  weibo: (accountId) => weiboApi.getCollections(accountId).then(r => r.data?.list || []),
  weixin_gzh: (accountId) => weixinGzhApi.getCollections(accountId, '视频合集').then(r => r.data?.list || []),
  // 抖音只有 mix_id / mix_name,且后端放在 data.mix_list
  douyin: (accountId) => douyinImageApi.getMixList(accountId).then(r => r.data?.mix_list || []),
  // 头条合集接口返回 {compilationId, title, total},归一为 {id, name, desc}
  toutiao: (accountId) => toutiaoApi.searchCompilation(accountId, '').then(r => (r.data?.list || []).map(it => ({
    id: it.compilationId,
    name: it.title,
    desc: it.total ? `${it.total} 个` : '',
  }))),
}

const collectionOptions = reactive({})   // fieldKey -> [{ id, name, desc }]
const loadingMap = reactive({})

function normalizeCollections(platformKey, raw) {
  const isDouyin = platformKey === 'douyin'
  return (raw || [])
    .map(item => {
      const id = isDouyin ? item.mix_id : item.id
      const name = isDouyin ? item.mix_name : item.name
      let desc = ''
      if (platformKey === 'xiaohongshu' && item.note_num != null) {
        desc = item.note_num > 0 ? `共 ${item.note_num} 篇` : '暂无内容'
      } else if (isDouyin && item.video_count != null) {
        desc = `${item.video_count} 个视频`
      }
      return { id, name, desc }
    })
    .filter(c => c.name)
}

async function loadCollectionData(f) {
  const accountId = props.account?.id
  if (!accountId) return
  const platformKey = platformConf.value?.key
  const fetcher = COLLECTION_FETCHERS[platformKey]
  if (!fetcher) {
    ElMessage.warning('该平台暂不支持获取合集数据,请手动输入名称')
    return
  }
  loadingMap[f.key] = true
  try {
    const raw = await fetcher(accountId)
    const list = normalizeCollections(platformKey, raw)
    collectionOptions[f.key] = list
    if (!list.length) ElMessage.info('该账号暂无合集,可手动输入名称')
    else ElMessage.success(`已获取 ${list.length} 个合集,聚焦输入框即可选择`)
  } catch (e) {
    ElMessage.error('获取合集数据失败:' + (e?.response?.data?.msg || e?.message || e))
  } finally {
    loadingMap[f.key] = false
  }
}

// 下拉数据源:已获取则按关键字过滤(空关键字 = 全部,聚焦即可见),未获取则为空(不影响手填)
function queryCollection(f, queryString, cb) {
  const all = collectionOptions[f.key] || []
  const kw = (queryString || '').trim().toLowerCase()
  const list = kw ? all.filter(c => c.name?.toLowerCase().includes(kw)) : all
  cb(list.map(c => ({ value: c.name, id: c.id, desc: c.desc })))
}

// 下拉回填:多数平台按名称匹配(v-model 已写入名称);
// 头条等 valueKey='id' 的平台按 ID 匹配,需覆盖为 ID;idKey 再把 id 同步到附属字段
function onCollectionSelect(f, item) {
  if (!item) return
  if (f.valueKey && item[f.valueKey] != null && item[f.valueKey] !== '') {
    form[f.key] = String(item[f.valueKey])
  }
  if (f.idKey && item.id != null && item.id !== '') form[f.idKey] = String(item.id)
}

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
  // 切换账号时清空上一个账号的合集缓存
  Object.keys(collectionOptions).forEach(k => delete collectionOptions[k])
  Object.keys(loadingMap).forEach(k => delete loadingMap[k])
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
    // 后端 updateUserinfo 会把 type/userName 一并 UPDATE;若只传 id 会导致这两列被置 NULL,
    // 而 user_info.type 是 INTEGER NOT NULL,置 NULL 触发 500。这里补上账号真实的 type/userName
    await accountApi.updateAccount({
      id: props.account.id,
      type: props.account.type,
      userName: props.account.userName ?? props.account.name,
      defaultConfig: payload
    })
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
/* 合集字段:输入框 + 「获取合集数据」按钮 */
.adc-fetch-row { display: flex; align-items: center; gap: 8px; }
.adc-fetch-input { flex: 1; min-width: 0; }
.adc-fetch-btn { flex-shrink: 0; }
.adc-opt-name { font-size: 13px; color: #334155; }
.adc-opt-desc { margin-left: 8px; font-size: 11px; color: #94a3b8; }
.adc-field-desc { font-size: 11px; color: #94a3b8; line-height: 1.5; margin-top: 2px; }
.adc-footer { display: flex; justify-content: space-between; align-items: center; }
.adc-footer-right { display: flex; gap: 8px; }
</style>
