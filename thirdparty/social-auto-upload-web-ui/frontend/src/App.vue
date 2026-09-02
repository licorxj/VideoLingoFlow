<template>
  <div class="layout">
    <!-- Sidebar -->
    <div class="sidebar" :class="{ expanded: !sidebarCollapsed }">
      <div class="sidebar-top">
        <div class="logo">
          <el-icon :size="18" class="logo-icon"><Promotion /></el-icon>
          <span v-if="!sidebarCollapsed" class="logo-text">千帆云递</span>
        </div>
        <button class="toggle-btn" @click="sidebarCollapsed = !sidebarCollapsed">
          <el-icon :size="16"><component :is="sidebarCollapsed ? Expand : Fold" /></el-icon>
        </button>
      </div>

<div class="sidebar-nav">
        <template v-for="item in navItems" :key="item.title">
          <el-tooltip v-if="sidebarCollapsed" :content="item.title" effect="dark" placement="right">
            <div
              class="nav-item"
              :class="{ active: activeMenu === item.path }"
              @click="router.push(item.path)"
            >
              <el-icon :size="20"><component :is="item.icon" /></el-icon>
            </div>
          </el-tooltip>
          <div
            v-else
            class="nav-item expanded-item"
            :class="{ active: activeMenu === item.path }"
            @click="router.push(item.path)"
          >
            <el-icon :size="20"><component :is="item.icon" /></el-icon>
            <span class="nav-label">{{ item.title }}</span>
          </div>
        </template>
      </div>

      <div class="sidebar-separator"></div>

      <div class="sidebar-bottom">
        <!-- 主题切换：放在 sidebar 底部，明显位置;折叠态只显图标,展开态显「图标 + 当前模式」 -->
        <button
          class="theme-toggle"
          :class="{ expanded: !sidebarCollapsed }"
          @click="appStore.toggleTheme"
        >
          <el-icon :size="16">
            <component :is="appStore.theme === 'dark' ? Sunny : Moon" />
          </el-icon>
          <span v-if="!sidebarCollapsed" class="theme-label">
            {{ appStore.theme === 'dark' ? '暗色' : '亮色' }}
          </span>
          <span v-if="!sidebarCollapsed" class="theme-hint">点击切换</span>
        </button>
        <template v-for="item in bottomItems" :key="item.path">
          <!-- 折叠态 -->
          <el-tooltip v-if="sidebarCollapsed" :content="item.title" effect="dark" placement="right">
            <div
              class="nav-item"
              :class="[ item._isSponsor ? 'sponsor-item' : '', { active: activeMenu === item.path } ]"
              @click="router.push(item.path)"
            >
              <el-icon :size="20"><component :is="item.icon" /></el-icon>
              <span v-if="item._isSponsor" class="sponsor-dot"></span>
            </div>
          </el-tooltip>

          <!-- 展开态 -->
          <div
            v-else
            class="nav-item expanded-item"
            :class="[ item._isSponsor ? 'sponsor-item sponsor-item--wide' : '', { active: activeMenu === item.path } ]"
            @click="router.push(item.path)"
          >
            <!-- 左侧品牌竖条 -->
            <span v-if="item._isSponsor" class="sponsor-bar"></span>

            <el-icon :size="item._isSponsor ? 22 : 20"><component :is="item.icon" /></el-icon>
            <span class="nav-label">{{ item.title }}</span>

            <!-- 打赏头像气泡（仅赞助项，展开态） -->
            <div v-if="item._isSponsor" class="sponsor-bubbles">
              <transition name="bubble" mode="out-in">
                <div
                  class="bubble"
                  :key="currentBubbleIndex"
                  :style="{ '--bubble-color': sponsorBubbles[currentBubbleIndex].color }"
                >
                  <div class="bubble-avatar">{{ sponsorBubbles[currentBubbleIndex].name[0] }}</div>
                  <span class="bubble-amt">+¥{{ sponsorBubbles[currentBubbleIndex].amount }}</span>
                </div>
              </transition>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- Right area -->
    <div class="main-area">
      <!-- Header -->
      <header class="header">
        <div class="breadcrumb">{{ pageTitle }}</div>
        <!-- 主题切换已移至 sidebar 底部(更显眼) -->
      </header>

      <!-- Content -->
      <main class="content">
        <router-view v-slot="{ Component }">
            <component :is="Component" :key="$route.path" />
          </router-view>
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  HomeFilled, User, Picture, Upload,
  Clock, Setting, Expand, Fold, Document, Notebook,
  Sunny, Moon, Promotion
} from '@element-plus/icons-vue'
import { useAppStore } from '@/stores/app'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()

const sidebarCollapsed = ref(false)

// 菜单项数据
const navItems = [
  { path: '/', icon: HomeFilled, title: '仪表盘' },
  { path: '/account-management', icon: User, title: '账号管理' },
  { path: '/material-management', icon: Picture, title: '素材管理' },
  { path: '/publish-center', icon: Upload, title: '视频发布' },
  { path: '/image-publish', icon: Picture, title: '图集发布' },
  { path: '/drafts', icon: Document, title: '草稿箱' },
  { path: '/publish-history', icon: Clock, title: '发布历史' },
  { path: '/changelog', icon: Notebook, title: '更新日志' }
]

// 底部区：系统设置
const bottomItems = [
  { path: '/settings', icon: Setting, title: '系统设置' }
]

const activeMenu = computed(() => route.path)

const pageTitle = computed(() => route.meta?.title || '')
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

.layout {
  display: flex;
  height: 100vh;
}

// ---- Sidebar ----
.sidebar {
  width: 64px;
  background: rgba($overlay-rgb, 0.03);
  border-right: 1px solid $border;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 0;
  flex-shrink: 0;
  transition: width $transition-slow;
  overflow: hidden;

  &.expanded {
    width: 200px;
    align-items: stretch;
    padding: 12px 12px;

    .sidebar-top {
      justify-content: space-between;
      padding-right: 0;

      .logo {
        // 展开态：胶囊形「图标 + 千帆云递」
        width: auto;
        height: 36px;
        padding: 0 12px;
        border-radius: 10px;
        gap: 8px;
        justify-content: flex-start;
        font-weight: 600;
        font-size: 14px;
        letter-spacing: 0.02em;

        .logo-text { display: inline; white-space: nowrap; }
      }
    }

    .sidebar-nav {
      align-items: stretch;
    }

    .nav-item.expanded-item {
      width: 100%;
      justify-content: flex-start;
      padding: 0 12px;

      .nav-label {
        display: inline;
        margin-left: 12px;
      }
    }

    .sidebar-bottom {
      align-items: stretch;
    }

    .sidebar-separator {
      margin: 8px 0;
      width: 100%;
    }
  }

  .sidebar-top {
    display: flex;
    align-items: center;
    margin-bottom: 16px;
    padding-right: 12px;
    gap: 4px;

    .logo {
      // 折叠态：圆形 36x36 图标
      width: 36px;
      height: 36px;
      border-radius: 50%;
      padding: 0;
      background: $gradient-brand;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0;
      color: #fff;
      flex-shrink: 0;
      overflow: hidden;
      transition: $transition-base;

      .logo-icon { font-size: 18px; }
      .logo-text { display: none; }
    }
  }

  .toggle-btn {
    width: 28px;
    height: 28px;
    border: none;
    border-radius: $radius-sm;
    background: transparent;
    color: $text-muted;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: $transition-base;
    flex-shrink: 0;

    &:hover {
      background: rgba($overlay-rgb, 0.06);
      color: $text-secondary;
    }
  }

  .sidebar-nav {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    flex: 1;
  }

  .sidebar-separator {
    height: 1px;
    background: $border;
    margin: 8px 12px;
    width: calc(100% - 24px);
  }

  .sidebar-bottom {
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .nav-item {
    width: 40px;
    height: 40px;
    border-radius: $radius-base;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: $transition-base;
    color: $text-muted;
    white-space: nowrap;
    position: relative;

    &:hover {
      background: rgba($overlay-rgb, 0.06);
      color: $text-secondary;
    }

    &.active {
      background: $gradient-brand;
      color: #fff;
    }

    .nav-label {
      display: none;
      font-size: 13px;
      font-weight: 500;
    }
  }
}

// ---- Main Area ----
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;

  .content {
    flex: 1;
    background: $bg-base;
    padding: 0;
    overflow-y: auto;
  }
}

.header {
  height: 48px;
  background: rgba($overlay-rgb, 0.02);
  border-bottom: 1px solid $border;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;

  .breadcrumb {
    color: $text-primary;
    font-size: 15px;
    font-weight: 600;
  }

  .header-right {
    // 主题切换已移至 sidebar-bottom（保留 flex 以备未来扩展）
    display: flex;
    align-items: center;
    gap: 8px;
  }
}

// 主题切换按钮：sidebar 底部，胶囊形状，「图标 + 当前模式 + 提示」
.sidebar .sidebar-bottom .theme-toggle {
  width: 36px;
  height: 36px;
  margin: 0 auto 8px;
  border: 1px solid $border;
  border-radius: 18px;
  background: var(--sidebar-theme-toggle-bg, rgba($overlay-rgb, 0.05));
  color: $text-secondary;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: $transition-base;
  position: relative;
  overflow: hidden;

  &:hover {
    background: var(--sidebar-theme-toggle-hover-bg, rgba($brand-start, 0.12));
    color: $brand-start;
    border-color: rgba($brand-start, 0.3);
    transform: translateY(-1px);
  }

  .theme-label,
  .theme-hint { display: none; }

  // 展开态：胶囊变宽,显模式名 + 「点击切换」提示
  &.expanded {
    width: 100%;
    height: 40px;
    padding: 0 12px;
    justify-content: flex-start;
    gap: 8px;
    font-size: 13px;
    font-weight: 500;
    border-radius: 10px;

    .theme-label {
      display: inline;
      flex: 1;
      text-align: left;
      letter-spacing: 0.02em;
    }
    .theme-hint {
      display: inline;
      font-size: 11px;
      color: $text-muted;
      padding: 2px 6px;
      border-radius: 4px;
      background: rgba($overlay-rgb, 0.06);
    }
    &:hover .theme-hint {
      background: rgba($brand-start, 0.15);
      color: $brand-start;
    }
  }
}
// 暗色模式下的微调
html.dark .sidebar .sidebar-bottom .theme-toggle {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.08);

  &:hover {
    background: rgba($brand-start, 0.18);
    border-color: rgba($brand-start, 0.4);
  }

  .theme-hint { background: rgba(255, 255, 255, 0.06); }
}

.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: opacity 150ms ease, transform 150ms ease;
}
.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
